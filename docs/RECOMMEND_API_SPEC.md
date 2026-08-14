# 추천 API 명세서 (FastAPI)

## 1. 개요

- **역할**: 냉장고 재료 텍스트 + 식사 시간대를 입력받아, 셰프(한식/중식/양식)별로 가장 어울리는 레시피 1개씩을 추천한다.
- **호출 흐름**: `React → Spring Boot(`/api/recommend`) → FastAPI(`/recommend`) → Spring Boot → React`
  - React는 FastAPI 주소를 모른다. Spring Boot가 내부적으로만 FastAPI를 호출한다.
  - FastAPI는 DB에 직접 접근하지 않는다. 후보 레시피 목록은 Spring이 조회해서 요청 본문에 함께 넘겨준다. (아래 3번 참고)
- **Base URL (개발)**: `http://localhost:8000`

## 2. 공통 Enum 값

DB 스키마와 동일한 값을 그대로 사용한다 (Spring이 응답을 그대로 저장할 수 있도록).

| 구분 | 값 |
|---|---|
| `meal_time` | `BREAKFAST`, `LUNCH`, `DINNER`, `LATE_NIGHT` |
| `chef_code` (genre) | `KOREAN`, `CHINESE`, `WESTERN` |

## 3. `POST /recommend`

냉장고 재료 텍스트를 분석해 셰프 3명(한식/중식/양식) 각각의 추천 레시피 1개씩을 반환한다. "다른 메뉴 보기(새로고침)" 요청도 같은 엔드포인트를 쓰되, `exclude_recipe_ids`로 이전에 보여준 레시피를 제외한다.

### 요청

```json
{
  "raw_ingredients_text": "계란 2개랑 김치 200g, 참치캔밖에 없어요",
  "meal_time": "DINNER",
  "conditions": ["간단하게", "15분이내"],
  "exclude_ingredients": ["두부"],
  "exclude_recipe_ids": {
    "KOREAN": [],
    "CHINESE": [],
    "WESTERN": []
  },
  "candidate_recipes": [
    {
      "recipe_id": 101,
      "chef_code": "KOREAN",
      "name": "참치김치 계란찜",
      "cooking_time_min": 12,
      "annoyance_score": 1.5,
      "knife_level": 0,
      "dish_count": 1,
      "image_url": "https://.../img.jpg",
      "ingredients": ["계란", "김치", "참치"]
    }
  ]
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `raw_ingredients_text` | string | O | 사용자가 입력한 재료 원문 (자연어) |
| `meal_time` | string (enum) | O | 아침/점심/저녁/야식 |
| `conditions` | string[] | X | "간단하게", "맵지 않게" 등 사용자가 선택한 조건 태그 |
| `exclude_ingredients` | string[] | X | 알레르기·비선호 재료 (후보에서 제외) |
| `exclude_recipe_ids` | object | X | 셰프별로 이미 보여준 `recipe_id` 목록 (새로고침 시 중복 방지) |
| `candidate_recipes` | array | O | Spring이 DB(`recipes` + `recipe_ingredients` + `recipe_meals` JOIN)에서 조회해 넘기는 후보 레시피 목록. FastAPI는 이 안에서만 골라서 점수를 매긴다 |

> `candidate_recipes`를 요청에 포함하는 이유: FastAPI가 DB 접근 없이 순수 계산만 담당하도록 하기 위해서다. Spring이 `is_active = TRUE`이고 `meal_time`이 일치하는 레시피만 미리 걸러서 넘겨주면 FastAPI 부담이 줄어든다.

### 응답

```json
{
  "parsed_ingredients": ["계란", "김치", "참치"],
  "normalized_ingredient_ids": [12, 7, 33],
  "portion_hint": "1인분 기준으로 딱 맞는 양이에요.",
  "results": {
    "KOREAN": {
      "recipe_id": 101,
      "name": "참치김치 계란찜",
      "cooking_time_min": 12,
      "annoyance_score": 1.5,
      "knife_level": 0,
      "dish_count": 1,
      "image_url": "https://.../img.jpg",
      "ingredients": ["계란", "김치", "참치"],
      "message": "대충 섞어도 맛있어서 실패가 거의 없어요.",
      "substitute_tip": "참치이(가) 없다면 햄 또는 스팸으로 대체해도 좋아요.",
      "match_score": 82.5
    },
    "CHINESE": { "...": "동일 구조" },
    "WESTERN": { "...": "동일 구조" }
  }
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `parsed_ingredients` | string[] | 원문에서 정규화된 표준 재료명 |
| `normalized_ingredient_ids` | int[] | `ingredients.ingredient_id` 목록 — `recommend_logs.normalized_ingredient_ids`에 그대로 저장 가능 |
| `portion_hint` | string \| null | 분량 힌트 문구 |
| `results.{KOREAN\|CHINESE\|WESTERN}` | object \| null | 셰프별 추천 결과. 후보가 없으면 `null` |
| `results[*].match_score` | number | 매칭 점수 (0~100) — `recommend_log_results.match_score`에 대응 |
| `results[*].substitute_tip` | string \| null | 재료 대체 팁 (없으면 `null`) |

### 에러 응답

| 상태 코드 | 상황 |
|---|---|
| `422` | 요청 필드 유효성 검증 실패 (FastAPI 기본 pydantic 에러) |
| `200` (빈 결과) | `candidate_recipes`가 비어있거나 조건에 맞는 레시피가 없으면 해당 셰프의 결과를 `null`로 반환 (에러 아님) |

## 4. Spring 쪽에서 이 응답으로 하는 일 (참고)

FastAPI는 계산만 하고, 아래 저장은 Spring이 담당한다.

1. `recommend_logs`에 요청 내용(`raw_ingredients_text`, `normalized_ingredient_ids`, `meal_time`, `conditions`) 저장
2. `recommend_log_results`에 셰프별 결과(`recipe_id`, `recommendation_rank`, `match_score`) 저장
3. 사용자가 최종 선택하면 `chef_selections`에 기록 (이건 별도 엔드포인트 `POST /api/recommend/select` 등에서 처리, FastAPI와 무관)

## 5. TODO / 확정 필요 사항

- [ ] `candidate_recipes`를 매 요청마다 Spring이 전부 조회해서 넘길지, 아니면 캐싱할지 결정
- [ ] `conditions`(간단하게/맵지 않게 등)를 실제 스코어링에 반영할지, 지금은 무시하고 로그용으로만 저장할지 결정
- [x] 비로그인 사용자도 추천 가능 — FastAPI 요청에는 애초에 `user_id`가 없어서 추가 작업 불필요. Spring이 `recommend_logs.user_id`를 `NULL`로 저장하면 끝 (컬럼이 nullable)
- [ ] **비로그인 사용자의 "선택하기"도 허용 — DB 스키마 수정 필요 (팀 승인 대기)**

  **확정된 제품 요구사항**: 회원 게시판 글 조회를 제외하면, 추천 결과 열람뿐 아니라 **선택하기까지 비로그인 상태로 가능해야 함**.

  **현재 문제**: `chef_selections.user_id`가 `NOT NULL`이고 `(recommend_log_id, user_id)` 복합 FK로 `recommend_logs`를 참조함 → 비로그인 요청은 `recommend_logs.user_id`가 `NULL`이라 이 복합 FK를 만족시킬 방법이 없어서, 선택 저장 자체가 불가능함.

  **제안하는 스키마 변경** (Railway DB에는 아직 미적용, 팀 동의 후 진행 예정):
  ```sql
  -- user_id를 NULL 허용으로 변경
  ALTER TABLE chef_selections MODIFY user_id BIGINT UNSIGNED NULL;

  -- 기존 복합 FK(recommend_log_id + user_id) 제거
  ALTER TABLE chef_selections DROP FOREIGN KEY fk_chef_selections_log_user;

  -- recommend_log_id 단독 FK로 재생성 (무결성은 이걸로 계속 보장)
  ALTER TABLE chef_selections
    ADD CONSTRAINT fk_chef_selections_log
    FOREIGN KEY (recommend_log_id) REFERENCES recommend_logs (recommend_log_id)
    ON DELETE RESTRICT;

  -- user_id는 있을 때만 회원 테이블과 연결 (NULL이면 체크 스킵)
  ALTER TABLE chef_selections
    ADD CONSTRAINT fk_chef_selections_user
    FOREIGN KEY (user_id) REFERENCES users (user_id)
    ON DELETE SET NULL;
  ```
  이 변경으로 로그인 여부와 무관하게 `recommend_log_id`만 유효하면 선택이 저장되고, 로그인한 사용자는 `user_id`도 함께 남아 추적 가능해진다.
