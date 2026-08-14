from fastapi import APIRouter
from pydantic import BaseModel
from kiwipiepy import Kiwi

router = APIRouter(prefix="/recommend", tags=["Recommend"])

# Kiwi 인스턴스는 내부적으로 형태소 분석 모델을 로딩하기 때문에 무겁다.
# 요청마다 새로 만들면 매번 로딩 비용이 들어서, 모듈 로드 시 한 번만 만들어 재사용한다.
kiwi = Kiwi()

# ---------- 요청/응답 스키마 ----------
# Spring이 보내주는 JSON 모양(요청) / FastAPI가 돌려주는 JSON 모양(응답)을 정의.
# pydantic이 이 클래스를 기준으로 요청을 검증하고, 응답을 JSON으로 직렬화해준다.

class CandidateRecipe(BaseModel):
    """Spring이 DB(recipes+recipe_ingredients+chefs)에서 미리 조회해서 넘겨주는 후보 레시피 1건.
    FastAPI는 이 목록 안에서만 골라서 점수를 매긴다 (DB에 직접 접근하지 않음)."""
    recipe_id: int
    chef_code: str  # KOREAN | CHINESE | WESTERN
    name: str
    cooking_time_min: int
    annoyance_score: float
    knife_level: int
    dish_count: int
    image_url: str | None = None
    ingredients: list[str]

class RecommendRequest(BaseModel):
    raw_ingredients_text: str  # 사용자가 입력한 자연어 원문. 예: "계란 2개랑 김치 200g"
    # 선택값. Spring이 이미 이 값으로 후보를 걸러서 넘겨주므로 FastAPI 로직에서는 안 쓰이고, 그대로 응답에도 없음.
    meal_time: str | None = None  # BREAKFAST | LUNCH | DINNER | LATE_NIGHT
    conditions: list[str] = []  # "간단하게" 등 조건 태그 (지금은 로직에 미반영, 로그용)
    exclude_ingredients: list[str] = []  # 알레르기 등으로 제외할 재료
    # 새로고침("다른 메뉴 보기") 시, 셰프별로 이미 보여준 recipe_id를 넘겨받아 다음 후보를 뽑는 데 사용
    exclude_recipe_ids: dict[str, list[int]] = {"KOREAN": [], "CHINESE": [], "WESTERN": []}
    candidate_recipes: list[CandidateRecipe]

class RecipeResult(BaseModel):
    recipe_id: int
    name: str
    cooking_time_min: int
    annoyance_score: float
    knife_level: int
    dish_count: int
    image_url: str | None
    ingredients: list[str]
    message: str
    substitute_tip: str | None
    match_score: float

class RecommendResponse(BaseModel):
    parsed_ingredients: list[str]  # 원문에서 뽑아낸 표준 재료명 목록
    portion_hint: str | None
    results: dict[str, RecipeResult | None]  # 셰프별 추천 결과. 후보가 없으면 None


# ---------- 재료 정규화 / 파싱 (kiwipiepy 형태소 분석 기반) ----------
#
# kiwipiepy는 문장을 형태소(의미를 가진 최소 단위) 단위로 쪼개고, 각 형태소에 품사 태그를 붙여준다.
# 예: "계란 2개랑" -> [계란/NNG, 2/SN, 개/NNB, 랑/JC]
#   NNG = 일반명사, SN = 숫자, NNB = 의존명사(단위: 개/g/등), JC = 접속조사
# 조사("랑", "은", "밖에" 등)가 자동으로 분리되기 때문에, 정규식으로 조사를 걷어낼 필요가 없다.
#
# TODO: 지금은 자주 쓰는 재료 위주로만 사전을 들고 있음.
# DB의 ingredients/ingredient_aliases 전체(예: "달걀"->"계란" 같은 별칭)를 반영하려면,
# Spring이 이 사전을 요청에 함께 넘겨주는 방식으로 확장 필요.
INGREDIENT_ALIASES = {
    "계란": "계란", "달걀": "계란", "김치": "김치", "참치": "참치", "참치캔": "참치",
    "햄": "햄", "스팸": "햄", "두부": "두부", "밥": "밥", "식빵": "식빵",
    "치즈": "치즈", "라면": "라면", "만두": "만두", "양파": "양파", "대파": "대파",
    "당근": "당근", "감자": "감자", "돼지고기": "돼지고기", "소고기": "소고기",
    "닭고기": "닭고기", "버섯": "버섯", "시금치": "시금치", "콩나물": "콩나물",
}

# 특정 재료가 없을 때 대신 쓸 수 있는 재료 추천 문구용 사전
SUBSTITUTES = {
    "참치": ["햄", "스팸", "계란"], "햄": ["참치", "스팸"], "계란": ["두부", "햄"],
    "두부": ["계란", "햄"], "김치": ["양파+고춧가루"], "식빵": ["밥", "또띠아"],
    "치즈": ["계란"], "라면": ["식빵", "밥"], "만두": ["두부", "라면"],
}

# 재료 후보로 취급할 품사: 일반명사(NNG), 고유명사(NNP)
NOUN_TAGS = {"NNG", "NNP"}


def normalize_ingredients(text: str) -> list[str]:
    """문장에서 명사 토큰만 뽑아, 사전에 등록된 재료명이면 표준 이름으로 변환해 모은다.
    예: "달걀"이 나오면 표준 재료명인 "계란"으로 바뀜."""
    tokens = kiwi.tokenize(text)
    found = set()
    for t in tokens:
        if t.tag in NOUN_TAGS and t.form in INGREDIENT_ALIASES:
            found.add(INGREDIENT_ALIASES[t.form])
    return list(found)


def parse_quantities(text: str) -> list[dict]:
    """숫자(SN) 토큰을 기준으로, 그 앞에 나온 가장 가까운 명사를 재료명으로,
    바로 뒤에 오는 단위명사(NNB, 예: "개")나 외국어 단위(SL, 예: "g")를 단위로 묶는다.
    예: "계란/NNG 2/SN 개/NNB" -> {"name": "계란", "qty": 2.0, "unit": "개"}"""
    tokens = kiwi.tokenize(text)
    quantities = []
    last_noun = None  # 지금까지 본 토큰 중 가장 최근의 명사를 기억해둔다
    for i, t in enumerate(tokens):
        if t.tag in NOUN_TAGS:
            last_noun = t.form
        elif t.tag == "SN" and last_noun:
            # 숫자 바로 다음 토큰이 단위를 나타내면 그 글자를 단위로 사용, 아니면 빈 문자열
            unit = tokens[i + 1].form if i + 1 < len(tokens) and tokens[i + 1].tag in ("NNB", "SL") else ""
            quantities.append({"name": last_noun, "qty": float(t.form), "unit": unit})
    return quantities


def substitute_tip(ingredients: list[str]) -> str | None:
    """추천된 레시피의 재료 중 SUBSTITUTES 사전에 있는 재료가 하나라도 있으면 대체 문구를 반환."""
    for name in ingredients:
        if name in SUBSTITUTES:
            return f"{name}이(가) 없다면 {' 또는 '.join(SUBSTITUTES[name])}(으)로 대체해도 좋아요."
    return None


def portion_hint(ingredients: list[str], quantities: list[dict]) -> str | None:
    """입력된 재료 수량 합계를 보고 "1인분 딱 맞음" / "2인분으로 늘려도 됨" 같은 문구를 생성.
    단위(개/g 등)를 구분하지 않고 숫자만 더하는 단순한 로직이라, 정확한 계량보다는 참고용 힌트다."""
    relevant = [q for q in quantities if any(q["name"] in ing or ing in q["name"] for ing in ingredients)]
    if not relevant:
        return None
    total = sum(q["qty"] for q in relevant)
    if total >= 5:
        return "재료가 넉넉해서 2인분으로 늘려도 좋아요."
    if total <= 1:
        return "딱 1인분 분량이에요. 정확히 이만큼만 준비하면 돼요."
    return "1인분 기준으로 딱 맞는 양이에요."


# ---------- 스코어링 ----------

def score_recipe(recipe: CandidateRecipe, ingredients: list[str], quantities: list[dict], excluded: list[str]) -> float:
    """레시피 하나가 입력 재료와 얼마나 잘 맞는지 점수를 매긴다.
    - 제외 재료가 포함돼 있으면 -999로 사실상 후보에서 탈락시킴
    - 입력 재료와 겹치는 개수 * 20점
    - 수량이 2개 이상으로 넉넉하게 입력된 재료가 쓰인 레시피는 소폭 가산점(qty_boost)"""
    text = recipe.name + " " + " ".join(recipe.ingredients)
    if any(name in text for name in excluded):
        return -999
    match = sum(1 for ing in ingredients if ing in text)
    qty_boost = sum(1 for q in quantities if q["qty"] >= 2 and q["name"] in text)
    return match * 20 + qty_boost


def pick_best(
    candidates: list[CandidateRecipe],
    chef_code: str,
    ingredients: list[str],
    quantities: list[dict],
    excluded_ingredients: list[str],
    excluded_ids: list[int],
) -> RecipeResult | None:
    """해당 셰프(chef_code)의 후보들 중, 이미 보여준 레시피(excluded_ids)는 빼고
    가장 점수가 높은 1개를 골라 RecipeResult로 조립한다. 후보가 없으면 None."""
    pool = [r for r in candidates if r.chef_code == chef_code and r.recipe_id not in excluded_ids]
    scored = [(r, score_recipe(r, ingredients, quantities, excluded_ingredients)) for r in pool]
    # 점수가 0 이하인 레시피(재료가 하나도 안 겹치거나 제외 재료 포함)는 후보에서 제거
    scored = sorted((x for x in scored if x[1] > 0), key=lambda x: x[1], reverse=True)
    if not scored:
        return None
    best, score = scored[0]
    return RecipeResult(
        recipe_id=best.recipe_id,
        name=best.name,
        cooking_time_min=best.cooking_time_min,
        annoyance_score=best.annoyance_score,
        knife_level=best.knife_level,
        dish_count=best.dish_count,
        image_url=best.image_url,
        ingredients=best.ingredients,
        message="입력한 재료와 가장 많이 일치하는 메뉴예요.",
        substitute_tip=substitute_tip(best.ingredients),
        match_score=score,
    )


# ---------- 엔드포인트 ----------

@router.post("", response_model=RecommendResponse, summary="재료 기반 셰프별 레시피 추천")
def recommend(req: RecommendRequest):
    # 1. 입력 텍스트에서 표준 재료명 / 수량 정보를 뽑아낸다
    ingredients = normalize_ingredients(req.raw_ingredients_text)
    quantities = parse_quantities(req.raw_ingredients_text)

    # 2. 셰프(한식/중식/양식) 각각에 대해 가장 잘 맞는 레시피 1개씩 선정
    results: dict[str, RecipeResult | None] = {}
    for chef_code in ("KOREAN", "CHINESE", "WESTERN"):
        excluded_ids = req.exclude_recipe_ids.get(chef_code, [])
        results[chef_code] = pick_best(
            req.candidate_recipes, chef_code, ingredients, quantities,
            req.exclude_ingredients, excluded_ids,
        )

    # 3. 응답 조립 (재료를 하나도 못 찾았으면 안내용 기본값 사용)
    return RecommendResponse(
        parsed_ingredients=ingredients or ["입력 재료"],
        portion_hint=portion_hint(ingredients, quantities),
        results=results,
    )
