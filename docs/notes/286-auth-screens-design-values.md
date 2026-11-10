---
issue: 286
date: 2026-11-10
owner: Pandyo
plan: 286-auth-screens.md
supersedes: []
---

# 인증·사용자 관리 화면의 디자인 속성 기록 (`0-Ticket.pen`)

`.pen`을 Pencil MCP로 프레임마다 읽은 값이다. 코드를 쓰기 전에 적었고, 구현은 이 값을 그대로 따른다. 읽지 못한 값은 "읽지 못함"이다. 약어: `lay` 배치 방향(없으면 가로), `gap`, `pad`(위·오른쪽·아래·왼쪽 또는 [세로,가로]), `ji` 주축 정렬, `ai` 교차축 정렬, `str` 테두리 색, `sw` 두께, `cr` 모서리 반경, `fs` 글자 크기, `fw` 굵기, `lh` 줄 높이(배수), `ls` 자간.

## 범위

| # | id | 프레임 | 화면 | 이번 작업 |
|---|---|---|---|---|
| 15 | C2NBcv | Login | 로그인 | 맞춤 |
| 16 | u3Y6pW | Sign up | 회원가입 | 맞춤 |
| 17 | AOayi | Dashboard (Logged out) | 로그아웃 대시보드 | 범위 밖(사람 결정) |
| 18 | KBqVK | Login · states | 로그인 상태 5종 + 로딩 | 맞춤 |
| 19 | ssP7L | Sign up · states | 가입 완료 / 409 / 422 | 맞춤 |
| 20 | DupGF | Password change · forced | 강제 비밀번호 변경 | 맞춤 |
| 21 | JoCjs | Dashboard · logged in (admin) | admin 대시보드 | 사이드바만(흐름 영역은 #274에서 맞춤) |
| 22 | zsFXl | Dashboard · analyst | analyst 대시보드 | 사이드바만 |
| 23·24 | GrHTU·lkrFB | Settings (+ 현재 비밀번호 오류) | 설정 페이지 | **그대로 둠**(사람 결정: 설정 버튼과 같은 취급) |
| 25 | gRZl1 | Error · 403 permission_denied | 권한 없음 | 맞춤 |
| 26 | cYbti | Error · 503 db_unavailable | 서버 연결 불가 | 맞춤 |
| 27 | b2dUw | Error · 403 origin_not_allowed | 접속 주소 거부 | 맞춤 |
| 28 | xhfKy | Users · list (pending) | 사용자 목록 | 맞춤 |
| 29 | G3TMc | Users · empty (rejected) | 빈 목록 | 맞춤 |
| 30 | ACsy7 | Users · action panel (pending) | 가입 승인 패널 | 맞춤 |

## 변수 ↔ style.css

| `.pen` 변수 | 값 | style.css |
|---|---|---|
| `$surface` | #ffffff | `--surface` |
| `$canvas` | #f5f7fb | `--page` |
| `$accent` | #2e66d2 | `--accent` |
| `$text-primary` | #23334d | `--ink` |
| `$border` | #ebeff5 | `--border` |
| `$radius-card` | 18 | (CSS에 숫자로 18px, 변수 없음) |
| `$space-card` | 24 | (카드 패딩 24px) |
| `$sidebar` | #101d35 | 사이드바는 컴포넌트에서 #000000을 직접 쓴다. 변수는 어디에도 쓰이지 않는다 |
| `$font-body` | Inter | 본문 글꼴 |

그 밖의 색(#6b7b95 `--muted`, #d5dce8 `--input-border`, #8a99b3 `--placeholder`)은 변수에 없는 리터럴이다. 같은 값이 반복되는 것만 변수로 만든다.

## 15·16·20 로그인 / 가입 / 강제 변경 (960×925, fill `$canvas`, clip)

| 노드 | 크기 | 속성 |
|---|---|---|
| Brand Panel | 400×925 | lay vertical, pad 40, ji space_between, clip. fill 3겹: #000000 → radial 중심(1,0) 회전 -157.499° 크기(1.5713,1.0525) #7689b066→#2e66d200 → radial 중심(0.1,1) 크기(1.4,0.7) #2e66d266→#2e66d200. (가입 16은 두 광택의 쌓는 순서만 반대) |
| Logo | 184×125 | gap 11, pad [0,6], ji space_between, ai center. 마크 56×78 이미지 `o-ticket-mark.png` contain. 글자 박스 111×78 lay vertical gap 7 pad [3.5,0,0,0] ji center |
| 0-Ticket | text | #ffffff, Michroma 20, fw 750, lh 1.5, ls -0.7 |
| SECURITY OPERATIONS | text | #8596b1, Jura 10, fw 500, lh 1.5, ls 1.5, "AI Agent-based/SOC Automation" |
| Tagline | 320×163 | lay vertical gap 14 |
| Headline | text | #ffffff Inter 26 fw 600 lh 1.35 |
| Description | text | #8596b1 Inter 14 lh 1.6 |
| Copyright | text | #637795 Inter 12 "© 2026 Ø-Ticket" |
| Form Area | 560×925 | lay vertical, ji center, ai center, fill `$canvas` |
| Form Card | 400×(436 로그인 / 618 가입 / 606 강제) | lay vertical gap 22 pad 36 fill `$surface` str `$border` sw 1(inner) cr 18, 그림자 없음 |
| Heading | 328×34 | lay vertical gap 8. Title Inter 28 fw 700 `$text-primary` |
| Fields | 328 폭 | lay vertical gap 16 |
| Form-Field(컴포넌트) | 328×72 | lay vertical gap 8. Label Inter 13 fw 600 `$text-primary`. Input 328×48 pad [0,14] ai center fill `$surface` str #d5dce8 sw 1 cr 10, Placeholder Inter 15 #8a99b3. Hint(꺼짐 기본) Inter 12 #6b7b95 |
| Form-Field 오류 | 328×95 | Input str #cf4c4c, 입력된 값은 글자색 #23334d, Hint가 켜져 Inter 12 #cf4c4c |
| 로그인 버튼(15) | 328×48 | fill `$accent` cr 10 ji/ai center, Label Inter 16 fw 600 #fff |
| 가입 버튼(16) | 328×48 | 로그인 버튼과 같음 |
| Reset Notice(15) | 328×18 | Inter 12 #6b7b95 lh 1.5 |
| Switch Link | 328×16 | gap 6 ji center. 질문 Inter 13 #6b7b95, 링크 Inter 13 fw 600 `$accent` |
| 15 | | 순서: Heading, Fields, 버튼, Reset Notice, Switch Link |
| 16 | | 순서: Heading, Fields, 버튼, Switch Link. 필드: 아이디(힌트 "사용할 수 있는 문자: a-z 0-9 . _ -") 95, 표시 이름 72, 비밀번호(힌트 "12~128자로 입력해 주세요.") 95, 비밀번호 확인 72 |
| 16 플레이스홀더 | | "영문 소문자·숫자 3~64자", "화면에 표시될 이름", "비밀번호 입력", "비밀번호 다시 입력" |
| 20 | | 순서: Heading, Banner info(328×81), Fields(271), 버튼(**328×44**, Button-Primary, Label Inter 14 fw 600), Logout Link |
| Banner info(20) | 328×81 | gap 10 pad [12,14] fill #edf3ff cr 10. Icon 16 #2e66d2. Text lay vertical gap 3: Title Inter 13 fw 700 lh 1.4 #23428a, Body Inter 12 lh 1.5 #23428a |
| Logout Link(20) | 328×16 | gap 6 ji/ai center. 아이콘 14 #6b7b95 + "로그아웃" Inter 13 fw 500 #6b7b95 |
| 20 필드 | | "현재 비밀번호"(플레이스홀더 "현재(임시) 비밀번호 입력"), "새 비밀번호"(힌트 "12~128자 · 현재 비밀번호와 달라야 해요."), "새 비밀번호 확인" |

## 18 로그인 상태 판 (1416×1255 lay vertical gap 36 pad 60 fill `$canvas`)

카드는 15와 같은 Form Card(392~477 높이). 상태별 차이만 적는다. 로딩 카드 말고는 카드 위쪽(Heading 아래)에 배너가 들어간다.

| 상태 | 배너 | 버튼 |
|---|---|---|
| 로딩 | 없음. 입력 잠금 | ref 328×44 "로그인 중…" (스피너 켜짐). Reset Notice 없음 |
| invalid_credentials | error: fill #fff0f0, 아이콘 #cf4c4c, 글자 #7a2b2b. 제목 "아이디 또는 비밀번호가 올바르지 않아요" / 본문 "입력한 내용을 확인한 뒤 다시 시도해 주세요." | ref 328×44 |
| unauthenticated | info: #edf3ff, 아이콘 #2e66d2, 글자 #23428a. "세션이 만료되었어요" / "다시 로그인하면 보던 화면으로 돌아가요." 입력칸은 비어 있고 플레이스홀더 | ref 328×44 |
| account_pending | **warn**: #fff7e6, 아이콘 #c98a12, 글자 #7a5410. "승인 대기 중인 계정이에요" / "관리자가 가입을 승인하면 로그인할 수 있어요." | ref 328×44 |
| account_rejected | error. "가입이 거절된 계정이에요" / "자세한 내용은 관리자에게 문의해 주세요." | ref 328×44 |
| account_disabled | error. "사용이 중지된 계정이에요" / "계정 사용 재개는 관리자에게 요청해 주세요." | ref 328×44 |

배너 모양(공통): gap 10 pad [12,14] cr 10, 아이콘 16, Title Inter 13 fw 700 lh 1.4, Body Inter 12 lh 1.5, Text 박스 lay vertical gap 3. 상태 카드에는 15의 Reset Notice가 없다. 상태 판의 버튼이 44인 것은 15·16(48)과 다르다. 15·16은 페이지 프레임을 따른다.

## 19 가입 상태 판 (1416×898)

| 상태 | 카드 |
|---|---|
| 201 | 높이 371. Success Mark 48×48 fill #e9f8f0 cr 24, 체크 아이콘 24 #1f8f5f. Heading "가입 신청이 완료됐어요"(Inter 28 fw 700). Signup Summary 328×107 lay vertical gap 10 pad 16 fill #f7f9fc cr 10: 줄마다 ji space_between, 라벨 Inter 13 #6b7b95 / 값 Inter 13 fw 600 `$text-primary` — "아이디", "표시 이름", "상태"(값은 Badge pending 58×23 pad [4,9] fill #fff7e6 cr 20, "승인 대기" Inter 10 fw 550 #b7791f). 버튼 "로그인 화면으로" 328×44: **보조 버튼** fill `$surface` str #d5dce8 sw 1 cr 10, Label Inter 14 fw 600 #23334d |
| 409 | 16과 같은 카드. 아이디 오류: Input str #cf4c4c, Hint "이미 사용 중인 아이디예요. 다른 아이디를 입력해 주세요." #cf4c4c. 버튼 328×44 |
| 422 | 필드 5개가 모두 오류. 아이디 "a-z 0-9 . _ - 만 사용해 3~64자로 입력해 주세요.", 표시 이름 "표시 이름을 입력해 주세요.", 비밀번호 "12~128자로 입력해 주세요.", 확인 "비밀번호가 일치하지 않아요." (이 판의 표시 이름 플레이스홀더는 "표시 이름 입력", 페이지 16은 "화면에 표시될 이름" — 페이지 16을 따른다) |

## 사이드바 (컴포넌트 Shell-Sidebar-Auth H47BL2, 224×925)

lay vertical, gap 20, pad [32,20,24,20], fill #000000. Logo(위 15와 같음). Nav 184폭 lay vertical gap 7. 항목 Nav-*: 184×47 gap 14 pad [13,14] ai center cr 9, 아이콘 20 #b7c5dc, 라벨 Inter 17 #b7c5dc. 활성 항목은 fill `$accent` + 그림자(0,5,blur 20 #060f2633)와 흰 글자. 순서: DashBoard, Alert/Event, Ticket, Incident, Case, Hunting, "관리" 라벨(184×26 pad [12,14,2,14], Inter 10 fw 650 ls 1.5 #637795), Ticket 정책(sliders-horizontal), 사용자 관리(users). Spacer 124. User Area 184×102 lay vertical gap 12 pad-top 16 상단 테두리 1px #29364b:
- User Row 184×42 gap 10 ai center: Avatar 36 원 fill #263650 str #42536d sw 1, 이니셜 Inter 14 fw 650 #d8e2f2. User Info lay vertical gap 4: 이름 Inter 14 fw 600 #d8e2f2, Role Badge 높이 18 pad [0,8] cr 9 fill #1b3a73 글자 #8fb4ff Inter 10 fw 650(analyst는 fill #1f2c42, 글자 #9fb0c8). **설정 타일**(44×42, str #42536d sw 1 cr 8, 아이콘 15 + "설정" Inter 10 fw 500 #9fb0c8): 사람 결정으로 모양·동작을 지금 구현 그대로 둔다.
- 로그아웃 184×32 gap 6 ji/ai center str #42536d sw 1 cr 8, 아이콘 14 + "로그아웃" Inter 12 fw 500 #b7c5dc.
- 21·22: 22(analyst)는 권한 없는 메뉴 3개를 숨기지 않고 opacity 0.35로 보인다. 지금 구현은 숨긴다(계획). 로직이라 바꾸지 않는다.

## 25~27 오류 화면 (Main 736×925: Content lay vertical gap 18 pad [26,24], Footer)

Page Heading 688×38: 제목 Inter 29 fw 800 lh 1.3 ls -1 #162841. Error State 688×761: lay vertical gap 14 pad 40 ji/ai center fill `$surface` str `$border` sw 1 cr 18. Icon Circle 56 원(cr 28), 아이콘 26. 제목 Inter 21 fw 700 `$text-primary`. 본문 420폭 Inter 14 lh 1.6 #6b7b95. Code Chip pad [4,10] fill #f0f3f7 cr 6, JetBrains Mono 11 #64748b. Actions gap 10, 버튼 44.

| 프레임 | 원 fill / 아이콘색 | 제목 | 칩 | 버튼 |
|---|---|---|---|---|
| 25 | #fff7e6 / #c98a12 (lock) | 이 화면을 볼 권한이 없어요 | 403 · permission_denied | 대시보드로 이동(130×44) |
| 26 | #fff0f0 / #cf4c4c | 서버에 일시적으로 연결할 수 없어요 | 503 · db_unavailable | 다시 시도(92×44) + 대시보드로 이동 |
| 27 | #fff7e6 / #c98a12 | 허용되지 않은 접속 주소예요 | 403 · origin_not_allowed | 다시 시도 |

본문: 25 "계정에 필요한 권한(user.read)이 없어요. 권한이 필요하면 관리자에게 요청해 주세요."(권한 이름은 화면마다 다르다), 26 "데이터베이스에 연결하지 못했어요. 입력한 내용은 그대로 유지돼요. 잠시 후 다시 시도해 주세요.", 27 "현재 접속한 주소는 변경 요청이 허용된 목록에 없어요. 계정 권한과는 관계없어요. 관리자에게 접속 주소 등록을 요청해 주세요." 아이콘 이름은 읽지 못함(lock 외).

## 28·29 사용자 목록

User List 688폭: lay vertical gap 14 pad 24 fill `$surface` str `$border` cr 18. 제목 "사용자 목록" Inter 15 fw 650 ls -0.3 `$text-primary`. Status Tabs 32높이 gap 8 ai center: "상태" Inter 11 fw 500 #8A96A9; 탭 pad [0,14] cr 16 str #DDE4EE fill #FFFFFF 글자 Inter 12 fw 500 #64748B; 선택 탭 fill #EDF3FF str #447EE3 글자 #447EE3 fw 650. User Table 640폭 str #E2E8F0 sw 1 cr 10: Header 38높이 gap 12 pad [0,16] ai center fill #F7F9FC 아래 테두리 #EEF2F6, 라벨 Inter 10 fw 600 #8A96A9, 열 폭 146/90/64/74/74/74 + Chevron 14. 행 52높이 gap 12 pad [0,16] ai center fill #fff 아래 테두리 #EEF2F6: 아이디 Inter 13 fw 600 #23334d(146), 표시 이름 Inter 12 #23334d(90), 역할 Badge(52×23 pad [4,9] fill #f0f3f7 cr 20 글자 Inter 10 fw 550 #64748b), 상태 Badge(승인 대기 fill #fff7e6 글자 #b7791f), 날짜 Inter 11 #64748b(74), "—", 끝 화살표 아이콘 14 #94a2b6. Pagination: Centered Pagination(가운데, pad-top 22): 이전/다음 32 원 fill #FFF str #E2E8F0, 현재 쪽 54×32 fill #F3F6FA cr 8 Inter 12 fw 650 "1 / 1". 29: 목록 높이 426, Empty State 640×300 lay vertical gap 10 ji/ai center: 원 48 fill #f0f3f7 아이콘 22 #8a99b3, 제목 Inter 16 fw 650 "거절된 사용자가 없어요", 설명 Inter 13 #6b7b95 "다른 상태 탭에서 사용자를 확인해 보세요."

## 30 작업 패널

Scrim 960×925 fill #0b142459. Action Panel 420×925 lay vertical fill `$surface` 그림자(바깥, x -8 y 0 blur 40 #12254030). Header 420×89 pad 24 ji space_between ai center 아래 테두리 #edf1f7: 작은 제목 "USER ACTION" Inter 9 fw 650 ls 1.8 #7588a4, 제목 "가입 승인" Inter 20 fw 650; 닫기 32×32 str #e2e8f0 cr 8 아이콘 16 #314158. Body lay vertical gap 20 pad 24: User Summary(gap 12 ai center): Avatar 44 원 fill #eef2f8 이니셜 Inter 16 fw 650, 이름 Inter 16 fw 650 / 아이디 Inter 12 #6b7b95, Badges gap 6(상태, 역할). Section 승인(gap 12): 제목 Inter 14 fw 650, Select "부여할 역할"(라벨 Inter 13 fw 600, 선택 372×44 pad [0,14] ji space_between fill `$surface` str #d5dce8 cr 10 값 Inter 14 + 화살표 16 #8a99b3, 안내 Inter 12 lh 1.5 #6b7b95), 버튼 "승인하기" 372×44. Section 거절(gap 12): 제목 Inter 14 fw 650, 안내 Inter 12 #6b7b95 "거절하면 이 계정으로 로그인할 수 없어요.", 버튼 "가입 거절" 372×44(스타일은 읽지 못함 → 보조 버튼 컴포넌트로 가정하지 않고 구현 때 노드를 읽어 적는다).

## 읽지 못한 것

- 아이콘 이름(사이드바 외), Button-Primary/Secondary/Danger가 패널 안에서 어느 것인지(승인하기·가입 거절), 줄 높이 값이 없는 글자의 기본 줄 높이, 가입 완료 카드의 Heading 부제(없음으로 보임).

## 구현과 비교 결과 (헤드리스 Chrome 960×925 캡처 ↔ Pencil 내보내기 PNG)

비교한 화면: 15, 16, 20(강제 변경), 25, 26, 28, 29, 30. 18·19(상태 판), 27, 21·22는 코드의 값·문구를 디자인 값과 대조만 했고 같은 크기의 캡처 비교는 하지 못했다(상태별 화면을 만들려면 가짜 서버가 더 필요하다; 27은 25·26과 같은 컴포넌트다).

### 디자인과 달라진 점(의도)

- 가입 완료(19): 계획의 "관리자 승인 후 로그인할 수 있다" 문장 대신 디자인대로 상태 배지("승인 대기")로 안내한다. 테스트의 해당 기대를 바꿨다.
- 로그인 버튼은 페이지 프레임(15·16)을 따라 48 높이다. 상태 판(18·19)과 강제 변경(20)의 버튼은 44다. 디자인 안에서 값이 다르다. 강제 변경은 44, 로그인·가입은 48로 각 프레임을 따른다.
- 표시 이름 플레이스홀더는 페이지 16의 "화면에 표시될 이름"이다(상태 판 19-422는 "표시 이름 입력").
- 22(analyst)는 권한 없는 메뉴를 흐리게 보이지만 구현은 숨긴다(계획, 로직이라 바꾸지 않음).
- 사이드바의 설정 타일은 사람 결정으로 지금 모양(작은 아이콘+글자)을 유지한다. 디자인은 44×42 테두리 타일이다.
- 오류 화면 본문의 권한 이름은 화면이 안다(`user.read`, `policy.read`, `dashboard.read`). 목록·패널 안 오류는 카드 없이 작게 보인다(`inline`).
- 아이콘: 디자인의 아이콘 이름을 읽지 못한 것(오류 26·27, 배너, 성공 표시, 빈 상태)은 선 아이콘(`line-icon.tsx`)으로 비슷한 모양을 썼다. 사이드바의 Incident·Case 아이콘은 #274 때 내보낸 값이라 디자인(shield-alert, folder-open)과 다르다. 바꾸지 않았다.

### 남은 차이

- 한글 글자 폭이 디자인보다 1~2% 좁다(헤드라인·제목이 한 줄에 더 들어간다). 제목에 쓰는 Inter 700 웨이트를 프로젝트가 불러오지 않는다.
- 사용자 표의 역할 열: 승인 대기 사용자는 `role`이 null이라 "—"이다(디자인 데이터는 analyst). 쪽 번호는 기존 "N/-" 형식이다(디자인 "1 / 1").
- 패널의 닫기 버튼에 키보드 포커스 고리가 처음부터 보인다(`showModal`이 첫 버튼에 포커스). 디자인엔 없다.
- 거절·중지 상태 배지 색은 읽지 못해 기본 회색이다.
- 활성 사용자 패널(31)·권한 편집(33~35)·정책(36~39)은 이번 범위 밖이라 스타일을 새로 맞추지 않았다. 버튼 클래스만 같은 `btn-*`를 쓴다.
