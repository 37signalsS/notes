# Betterleaks — поиск секретов в Git и за его пределами

**Актуально для:** Betterleaks v2 (release candidate, ветка `main`) / v1.x (ветка `v1.x`, maintenance)

## Определения

**Betterleaks** ([github.com/betterleaks/betterleaks](https://github.com/betterleaks/betterleaks)) — открытый сканер секретов, наследник Gitleaks. Разработан Заком Райсом (Zach Rice), автором Gitleaks, при спонсорстве Aikido — бельгийской компании, занимающейся защитой жизненного цикла разработки. Лицензия MIT; код на чистом Go (без CGO и Hyperscan), движок regex — re2, быстрый поиск по ключевым словам — ahocorasick.

**Секрет** — любые данные, компрометация которых нарушает безопасность: пароли, API-ключи, токены, приватные ключи.

**Правило (rule)** — описание того, что считать секретом: регулярное выражение, ключевые слова (`keywords`) для предварительного отбора, фильтры и выражение валидации.

**Drop-in replacement:** CLI-опции и конфиги Gitleaks продолжают работать в Betterleaks без правок — переход не требует переделки пайплайнов.

## Основные концепции

### Как работает

1. **Детекция:** правила с регулярными выражениями; поле `keywords` отсекает файла без характерных подстрок ещё до запуска regex.
2. **Фильтрация (два уровня):**
   - `prefilter` — глобальное выражение, выполняется до regex и видит только метаданные (`attributes`: путь, автор коммита, сообщение, дата и др.). Используется, чтобы целиком пропустить бинарные файлы, `node_modules`, `vendor`, коммиты ботов.
   - `filter` — глобальное или правило-уровневое выражение, выполняется после regex-совпадения и видит `attributes` и саму находку (`finding`): значение секрета, строку, rule id.
3. **Язык выражений — Expr** ([expr-lang.org](https://expr-lang.org)); CEL-конфиги принимаются для совместимости. Если выражение возвращает `true`, элемент пропускается или отбрасывается.
4. **Token efficiency вместо чистой энтропии:** строки разбиваются BPE-токенизатором — естественный текст и машинные credentials распадаются по-разному, что отсекает ложные срабатывания. Функция `entropy()` в фильтрах по-прежнему доступна.
5. **Валидация:** выражение `validate` проверяет, живой ли найденный секрет (асинхронные HTTP-запросы к API провайдера прямо из правила). По умолчанию выключена — включается флагом `-v`/`--validate` (в v1 — `--validation`). Флаг `-a`/`--analyze` дополнительно определяет identity и права доступа credential; `revoke` отзывает секрет через API провайдера, где это поддерживается.
6. **Подавление находок:** сигнатуры `betterleaks:allow` / `gitleaks:allow` в строке находки; файл `.betterleaksignore` с SHA-256 fingerprint точных значений (опционально HMAC-ключ).

### Почему важен поиск за пределами кода

Разработчик может (хотя статистика атак показывает обратное) не оставлять секретов в самом коде, но то, что пишут в issues, PR, комментариях, релизах и других публичных местах, он уже не уследит — а злоумышленник уследит. Betterleaks сканирует не только Git-историю, но и эти ресурсы.

### Источники сканирования

| Что сканировать | Команда |
| :--- | :--- |
| Файлы и директории | `betterleaks <path>` (или `filesystem`/`fs`) |
| Git-история, staged/unstaged diff, pre-receive hook | `betterleaks git [path-or-url]` |
| Один HTTP(S)-ответ или архив (кастомный адрес) | `betterleaks url <url>` |
| GitHub: репозитории, форки, PR, issues, discussions, релизы, actions, артефакты, гисты | `betterleaks github <url>` |
| GitLab: проекты, MR, issues, сниппеты, релизы, CI-jobs и артефакты | `betterleaks gitlab <url>` |
| Hugging Face: модели, датасеты, Spaces, discussions, PR, бакеты | `betterleaks huggingface <url>` (алиас `hf`) |
| S3 и S3-совместимые (R2, MinIO и др.) | `betterleaks s3 <url>` |
| Контейнерные образы, исторические слои, метаданные | `betterleaks container <image>` |
| Переданный через stdin контент | `betterleaks stdin` |
| Автовыбор источника по пути/URL | `betterleaks auto <target>` |

Без флагов сканирование только детектирует секреты, к провайдерам не обращается.

## Практические сценарии

### Установка

```bash
# Package managers (macOS/Linux)
brew install betterleaks
brew install --cask betterleaks/tap/betterleaks

# Fedora Linux
sudo dnf install betterleaks

# Контейнеры (стабильный v2)
docker pull ghcr.io/betterleaks/betterleaks:v2

# Go
go install github.com/betterleaks/betterleaks/v2@latest

# Из исходников
git clone https://github.com/betterleaks/betterleaks
cd betterleaks
make build
```

> До выхода стабильного v2 пакетные менеджеры и Docker-тег `latest` могут отдавать v1. Для v2 используйте `ghcr.io/betterleaks/betterleaks:v2`; v1 рядом с v2 ставится через `brew install --cask betterleaks/tap/betterleaks@1` (команда `betterleaks-v1`) или Docker-тег `:v1`.

### Сканирование локально

```bash
# текущая директория
betterleaks filesystem .

# несколько путей
betterleaks filesystem services/api infra/terraform

# полная история Git-репозитория
betterleaks git .

# только staged-изменения (pre-commit hook)
betterleaks git --staged

# unstaged-изменения отслеживаемых файлов
betterleaks git --unstaged

# коммиты, теги и reflog-сообщения в дополнение к патчам
betterleaks git . --include=commit-messages,tag-messages,reflogs

# ограниченная выборка истории
betterleaks git . --log-opts="--all --since='90 days ago'"

# JSON-отчёт
betterleaks git . --output findings.json
```

### Сканирование GitHub, GitLab, Hugging Face, S3

```bash
# история репозитория на GitHub
betterleaks github https://github.com/my-company/backend

# все репозитории организации
betterleaks github https://github.com/my-company

# только issues, PR и комментарии к ним (история репо исключена)
betterleaks github \
  --include=issues,prs,issue-comments,pr-comments \
  --exclude=repos \
  https://github.com/my-company

# логи GitHub Actions и их артефакты
betterleaks github --include=actions,action-artifacts https://github.com/my-company/backend

# один ресурс, например PR
betterleaks github https://github.com/my-company/backend/pull/1234

# группа и проект на GitLab
betterleaks gitlab https://gitlab.com/mygroup
betterleaks gitlab https://gitlab.com/mygroup/myproject --include issues,mrs,releases,ci-jobs

# модели и датасеты на Hugging Face
betterleaks hf https://huggingface.co/datasets/myorg/mydataset

# публичный S3-датасет
betterleaks s3 https://commoncrawl.s3.us-east-1.amazonaws.com/crawl-data/CC-MAIN-2018-17/segments/1524125937193.1/warc/

# кастомный адрес: скачать и просканировать один HTTP(S)-ответ
betterleaks url https://example.com/config.txt

# контент через stdin
cat some_file.txt | betterleaks stdin
```

Перед запуском задайте токены в окружении: `GITHUB_TOKEN`, `GITLAB_TOKEN` (для self-managed GitLab — `--base-url=https://gitlab.example.com/`), `HUGGINGFACE_TOKEN` или `HF_TOKEN`, для S3 — стандартные AWS-credentials и `--region`. Публичную Git-историю GitLab можно сканировать без токена; group/user-перечисление и API-ресурсы требуют токена.

### Конфигурация betterleaks.toml

```toml
# Глобальный prefilter: выполняется до regex, видит только attributes
prefilter = '''
matchesAny(attributes["path"], [
  `(?i)\.(?:bmp|gif|jpe?g|png|svg|tiff|pdf|exe)$`,
  `(?:^|/)node_modules(?:/.*)?$`,
  `(?:^|/)vendor(?:/.*)?$`
])
|| attributes["git.author_name"] == "renovate[bot]"
'''

# Глобальный filter: выполняется для каждого кандидата в секреты
filter = '''
containsAny(finding["secret"], [
  "EXAMPLE",
  "CHANGEME",
  "YOUR_API_KEY_HERE",
  "0000000000000000"
])
'''

# Правило
[[rules]]
id = "github-pat"
description = "GitHub Personal Access Token, risking unauthorized repository access."
regex = '''ghp_[0-9a-zA-Z]{36}'''
keywords = ["ghp_"]

# Правило-уровневый filter
filter = '''
(
    attributes["git.author_name"] == "ci-runner" &&
    matchesAny(attributes["path"], [`^mocks/`]) &&
    finding["secret"] contains "TESTING"
)
|| (entropy(finding["secret"]) <= 3.0)
'''

# Валидация: проверка, живой ли секрет (выполняется при включённой валидации)
validate = '''
let r = http.get("https://api.github.com/user", {
    "Accept": "application/vnd.github+json",
    "Authorization": "token " + finding["secret"]
  });
r.status == 200 && (r.json?.login ?? "") != "" ? {
    "result": "valid",
    "analysis": {
      "id": string(r.json?.id ?? ""),
      "username": r.json?.login ?? "",
      "scopes": strings.splitTrim(r.headers["x-oauth-scopes"] ?? "", ",")
    }
  } : r.status in [401, 403] ? {
    "result": "invalid",
    "reason": "Unauthorized"
  } : validate.unknown(r)
'''
```

Конфиг подключается явно (`--config betterleaks.toml`); `.betterleaks.toml` в целевых директориях автоматически не подгружается. `[extend]` наследует правила из другого конфига или встроенных defaults; `betterleaksMinVersion` и `minVersion` задают минимальные версии бинара и формата конфига Gitleaks.

### Валидация и анализ известного credential

```bash
# живой ли секрет (без повторного детектирования)
printf '%s\n' "$GITHUB_TOKEN" | betterleaks validate --rule github-pat

# только статус, например VALID
printf '%s\n' "$GITHUB_TOKEN" | betterleaks validate --rule github-pat --simple

# identity и права доступа
printf '%s\n' "$GITHUB_TOKEN" | betterleaks analyze --rule github-pat

# отзыв через API провайдера (где поддерживается правилом)
betterleaks revoke --rule github-pat

# какие rule-id поддерживают анализ / отзыв
betterleaks config show ids --analysis
betterleaks config show ids --revocation
```

### Тестирование правил

[Playground](https://betterleaks.com/playground) запускает Betterleaks в браузере как WASM-бинарь (~10 MB): вставьте текст в INPUT, отредактируйте TOML-правила в CONFIG, нажмите SCAN — находки появятся в LOGS.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| API-ресурсы GitHub/GitLab/HF не сканируются | Нет токена | Экспортируйте `GITHUB_TOKEN` / `GITLAB_TOKEN` / `HUGGINGFACE_TOKEN` (или `--token`) |
| `betterleaks` без аргументов показывает помощь | Источник не выбран | Укажите команду явно или используйте `auto` |
| Старые флаги v1 (`--validation-workers`, `--pre-commit`) не принимаются | v2 переименовал флаги | `--provider-workers`; для pre-commit используйте `--staged` |
| Конфиг игнорируется | Конфиг не выбран явно | `--config <path>`; авто-подгрузки `.betterleaks.toml` нет |
| Находка не подавляется allow-сигнатурой | Сигнатура — case-sensitive подстрока строки находки | `betterleaks:allow` или `gitleaks:allow`; свои — через `--allow-signature` |
| Валидация не выполняется | По умолчанию выключена | `-v`/`--validate` (или `BETTERLEAKS_VALIDATE=true`); `-a`/`--analyze` — плюс анализ |

## Лучшие практики

- **Свой конфиг в production:** не расширяйте upstream-default напрямую — поддерживайте свой набор правил, чтобы обновления Betterleaks не меняли поведение сканирования; новые upstream-правила ревьюйте перед adoption.
- **Shift Left:** pre-commit hook на `betterleaks git --staged` (в комплекте есть готовые хуки, сканирующие с `--redact`, чтобы коммит не зависел от сети и находки не попадали в лог); server-side — `pre-receive` hook с `betterleaks git --pre-receive`, отклоняющий push с утечками.
- **`.betterleaksignore` ревьюйте как allowlist-исключение:** записи — SHA-256 fingerprint точных значений; слабые секреты можно угадать по SHA-256 offline, защищайте файл (например, через CODEOWNERS). Для приватных fingerprint используйте HMAC-ключ (`--hmac-key` / `BETTERLEAKS_FINGERPRINT_HMAC_KEY`).
- **Параллелизм:** `-j`/`--jobs` задаёт concurrency детекции (по умолчанию `4 * GOMAXPROCS`).

## Дополнительная информация

- [Репозиторий и установка](https://github.com/betterleaks/betterleaks)
- [Документация: конфиг](https://github.com/betterleaks/betterleaks/blob/main/docs/config.md) и [сканирование](https://github.com/betterleaks/betterleaks/blob/main/docs/scanning.md)
- [Конфиг по умолчанию](https://github.com/betterleaks/betterleaks/blob/main/config/betterleaks.toml)
- [Playground](https://betterleaks.com/playground) — тестирование правил в браузере
- [Обзор на olks.cc](https://olks.cc/project/betterleaks) — источник заметки
- [Secrets Management Overview](../Concepts/secrets_management_overview.md) — секреты в контексте управления ими
- Go SDK: `go get github.com/betterleaks/betterleaks/v2` — сканер можно встроить как библиотеку; [MegaLinter](https://megalinter.io) поставляет Betterleaks из коробки
- Gitleaks остаётся стабильным проектом (автор продолжает выпускать security-патчи); Betterleaks — его преемник следующего поколения
