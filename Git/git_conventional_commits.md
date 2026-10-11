# Conventional Commits — спецификация и автоматизация версионирования

**Актуально для:** Conventional Commits v1.0.0; commitlint v19.x; git-cliff v2.x

## Определения

**Conventional Commits** — спецификация формата сообщений коммитов поверх Git, задающая легковесную структуру для облегчения чтения истории человеком и автоматизированной обработки утилитами сборки, версионирования и генерации документации.

**SemVer (Semantic Versioning)** — стандарт версионирования программного обеспечения формата `MAJOR.MINOR.PATCH`, правила которого напрямую маппятся на типы изменений Conventional Commits: исправления (`PATCH`), новый обратно совместимый функционал (`MINOR`), критические обратно несовместимые изменения (`MAJOR`).

**Scope (область действия)** — опциональный квалификатор контекста коммита, указываемый в круглых скобках сразу после типа (`type(scope): description`). Обозначает конкретный компонент инфраструктуры, микросервис, конфигурационный модуль или подсистему.

**Breaking Change** — изменение, нарушающее обратную совместимость API, схемы конфигурации, сетевого протокола или инфраструктурного интерфейса. Обозначается восклицательным знаком после типа/scope (`feat!:`, `fix(api)!:`) либо отдельной секцией в подвале (`BREAKING CHANGE:`).

**Git Trailer** — стандартизированный структурированный метаблок в подвале сообщения коммита (формата `Ключ: Значение` или `Ключ #Значение`), соответствующий спецификации RFC 822 и утилите `git interpret-trailers`. Применяется для ссылок на задачи, инциденты и соавторство.

**commitlint** — статический анализатор сообщений коммитов, выполняющий валидацию текста на соответствие правилам спецификации Conventional Commits в клиентских хуках Git и в CI/CD пайплайнах.

**git-cliff** — высокопроизводительный генератор истории изменений (changelog) на языке Rust, компилируемый в единый статический бинарный файл без внешних интерпретаторов. Оптимален для серверных и DevOps-сред.

**semantic-release** — инструмент полной автоматизации цикла релизов: анализирует коммиты по спецификации Conventional Commits, определяет следующую версию по SemVer, генерирует release notes, создаёт Git-тег и публикует артефакты.

---

## Базовые концепции

### Структура спецификации Conventional Commits

Формат сообщения строго регламентирован спецификацией v1.0.0:

```text
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Элементы структуры:

| Элемент | Обязательность | Правила оформления |
| :--- | :--- | :--- |
| `type` | Да | Префикс в нижнем регистре (`feat`, `fix`, `chore` и др.), задающий характер изменений. |
| `scope` | Нет | Имя компонента в круглых скобках в нижнем регистре без пробелов: `(helm)`, `(nginx)`, `(k8s)`. |
| `!` (маркер) | Нет | Восклицательный знак непосредственно перед двоеточием (`type!:` или `type(scope)!:`) сигнализирует о `BREAKING CHANGE`. |
| `: ` | Да | Двоеточие с обязательным пробелом после него, отделяющее заголовок от краткого описания. |
| `description` | Да | Краткое резюме изменений в повелительном наклонении, строчными буквами, без точки на конце (не более 50–72 символов). |
| `body` | Нет | Развёрнутое пояснение причин и сути изменений. Отделяется от заголовка пустой строкой. Строки переносятся на 72 символах. |
| `footer` | Нет | Секции метаданных (ссылки на трекер задач, фиксация BREAKING CHANGE, подписи). Отделяются от body пустой строкой. |

---

### Типы коммитов и связь с SemVer

Спецификация определяет основные типы, которые напрямую влияют на автоматическое повышение версий:

| Тип | Назначение | Влияние на SemVer | Пример в DevOps / SRE |
| :--- | :--- | :--- | :--- |
| `feat` | Добавление новой функциональности или инфраструктурной возможности | `MINOR` (+0.1.0) | `feat(prom): add disk IOPS saturation alert rule` |
| `fix` | Исправление ошибки, инцидента или некорректного поведения конфигурации | `PATCH` (+0.0.1) | `fix(nginx): resolve 502 bad gateway on upstream timeout` |
| `perf` | Оптимизация производительности, снижение потребления ресурсов CPU/RAM | `PATCH` (+0.0.1) / без релиза | `perf(sysctl): tune tcp_max_syn_backlog for high load` |
| `build` | Изменения в сборочных файлах, зависимостях, Dockerfile, Makefile | Без релиза / `PATCH` | `build(docker): optimize multi-stage build cache layers` |
| `ci` | Конфигурация пайплайнов CI/CD, раннеров, этапов линтинга и тестов | Без релиза | `ci(gitlab): add ansible-lint step to validation stage` |
| `docs` | Обновление runbook, документации архитектуры, disaster recovery планов | Без релиза | `docs(dr): update postgresql failover manual` |
| `style` | Правки форматирования кодовой базы/манифестов без изменения логики | Без релиза | `style(yaml): align indentation across ansible roles` |
| `refactor` | Реструктуризация конфигурации или кода без изменения внешнего поведения | Без релиза | `refactor(terraform): split network modules into subnets` |
| `test` | Добавление или исправление тестов (Molecule, bats, kubeconform) | Без релиза | `test(molecule): add verification scenario for nginx role` |
| `chore` | Рутинные задачи, обновление второстепенных файлов, ротация ключей | Без релиза | `chore(deps): bump debian base image tag to 12.5` |
| `revert` | Откат предыдущего коммита Git | По типу отката | `revert: undo feat(k8s): deploy vllm service` |

Любой тип с маркером `!` либо футером `BREAKING CHANGE:` форсирует повышение `MAJOR` версии (+1.0.0).

---

### Соглашения по Scope в инфраструктурных проектах

В системном администрировании, SRE и DevOps репозитории чаще всего содержат монорепозитории инфраструктуры (IaC), наборы ролей или манифестов. Стандартизация scope предотвращает хаос в журнале изменений:

| Категория инфраструктуры | Рекомендуемые Scope | Примеры коммитов |
| :--- | :--- | :--- |
| **Управление конфигурацией (Ansible/Puppet)** | По имени роли, сервиса или инвентаря | `feat(ansible-nginx): add brotli compression support`<br>`fix(ansible-users): enforce sudo group permissions` |
| **Оркестрация и контейнеры (Kubernetes/Helm/Docker)** | По ресурсу, чарту или образу | `feat(helm-ingress): configure rate-limiting annotations`<br>`fix(k8s-coredns): raise memory limit to prevent OOMKilled` |
| **Системные сервисы и ОС** | По сервису systemd, подсистеме ядра, сети | `fix(systemd-journald): cap storage limit to 2G`<br>`feat(iptables): restrict ssh access to management subnet` |
| **Мониторинг и наблюдаемость** | По стеку (Prometheus, Grafana, Vector, Loki) | `feat(prometheus): add high error rate alert for api upstream`<br>`fix(promtail): correct journald path mapping` |
| **Пайплайны (CI/CD)** | По пайплайну, раннеру или шагу | `ci(runner): update docker executor tags`<br>`fix(pipeline): cache molecule virtualenv directory` |

---

### Механизм Breaking Changes

Критические изменения, требующие вмешательства администратора или изменения зависимых систем при накатывании релиза, документируются двумя эквивалентными способами:

1. **Краткий маркер в заголовке (`!`):**
   ```bash
   git commit -m "feat(ansible-pgsql)!: drop support for postgresql 12"
   ```
2. **Подробный футер с описанием миграции (`BREAKING CHANGE:`):**
   ```text
   feat(helm-redis): migrate cluster configuration to standalone sentinel

   BREAKING CHANGE: Redis chart parameters `cluster.enabled` is replaced by
   `mode: sentinel`. Existing PVC volumes must be migrated manually.
   ```

---

### Футеры и Git Trailers

Футер оформляется в соответствии с соглашениями Git trailers. Допустимы ссылки на тикеты, инциденты и метаданные:

```text
fix(haproxy): mitigate syn flood vulnerability on external ingress

Rate limit connection bursts per IP using stick-tables.
Backpressure applied to non-whitelisted CIDR ranges.

Fixes: #1042
Refs: INC-8821
Signed-off-by: SRE Admin <sre@example.local>
```

---

## Практические сценарии

### Сценарий 1: Составление коммитов для задач системного администрирования и SRE

#### Задача А: Добавление нового правила мониторинга (Minor)
```bash
git commit -m "feat(prometheus): add alert rule for high disk latency

Trigger alert when average IO wait exceeds 200ms for 5 minutes.
Prevents unobserved database storage saturation.

Refs: MONITORING-204"
# → [master 8a3f12c] feat(prometheus): add alert rule for high disk latency
```

#### Задача Б: Экстренный патч лимитов контейнера (Patch)
```bash
git commit -m "fix(k8s-ingress): increase memory limit to 512Mi to prevent OOM"
# → [master 4b9c10d] fix(k8s-ingress): increase memory limit to 512Mi to prevent OOM
```

#### Задача В: Мажорное изменение конфигурации Nginx (Major)
```bash
git commit -m "feat(nginx)!: enforce tls 1.3 only on production edge

BREAKING CHANGE: TLS 1.0 and 1.1 ciphers are removed from all server blocks.
Legacy clients without TLS 1.3 support will fail to establish handshake."
# → [master c9110a2] feat(nginx)!: enforce tls 1.3 only on production edge
```

---

### Сценарий 2: Локальная валидация через нативный Shell-хук без Node.js

На серверах, bastion-хостах или в средах системного администрирования часто отсутствует Node.js/npm. Для принудительной проверки формата сообщений коммитов используется легковесный POSIX-совместимый хук `.git/hooks/commit-msg`:

```bash
# Создание хука commit-msg в локальном репозитории
cat << 'EOF' > .git/hooks/commit-msg
#!/bin/sh
set -e

COMMIT_MSG_FILE="$1"
FIRST_LINE=$(head -n 1 "$COMMIT_MSG_FILE")

# Игнорировать автоматически создаваемые коммиты merge и revert
if echo "$FIRST_LINE" | grep -qE '^Merge (branch|tag|remote-tracking branch)|Revert "'; then
  exit 0
fi

# Регулярное выражение для Conventional Commits:
# type(scope)!: description
PATTERN='^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([a-zA-Z0-9_.-]+\))?!?: [^[:space:]].+$'

if ! echo "$FIRST_LINE" | grep -qE "$PATTERN"; then
  echo " ОШИБКА: Сообщение коммита не соответствует спецификации Conventional Commits!" >&2
  echo " Получено: '$FIRST_LINE'" >&2
  echo " Ожидаемый формат: <type>[optional scope]: <description>" >&2
  echo " Допустимые типы: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert" >&2
  echo " Пример: feat(nginx): add cache-control headers" >&2
  exit 1
fi

# Проверка максимальной длины заголовка (72 символа)
LINE_LEN=$(printf "%s" "$FIRST_LINE" | wc -c)
if [ "$LINE_LEN" -gt 72 ]; then
  echo " ОШИБКА: Длина заголовка коммита ($LINE_LEN симв.) превышает лимит в 72 символа." >&2
  exit 1
fi

exit 0
EOF

chmod +x .git/hooks/commit-msg
```

#### Проверка работы хука:
```bash
# Попытка сделать некорректный коммит
git commit --allow-empty -m "fixed stuff in nginx config"
# →  ОШИБКА: Сообщение коммита не соответствует спецификации Conventional Commits!
# →  Получено: 'fixed stuff in nginx config'
# →  Ожидаемый формат: <type>[optional scope]: <description>

# Корректный коммит
git commit --allow-empty -m "fix(nginx): correct upstream keepalive timeout"
# → [master 21cf81e] fix(nginx): correct upstream keepalive timeout
```

---

### Сценарий 3: Настройка commitlint с кастомным набором Scope под инфраструктуру

Для проектов с Node.js окружением проверка формата настраивается через `@commitlint/cli` с декларативным контролем допустимых `scope`.

#### 1. Установка пакетов
```bash
npm install --save-dev @commitlint/cli@^19.0.0 @commitlint/config-conventional@^19.0.0
# → added 68 packages in 3s
```

#### 2. Создание файла конфигурации `.commitlintrc.json`
```json
{
  "extends": ["@commitlint/config-conventional"],
  "rules": {
    "scope-enum": [
      2,
      "always",
      [
        "ansible",
        "docker",
        "helm",
        "k8s",
        "nginx",
        "prometheus",
        "grafana",
        "systemd",
        "ci",
        "security",
        "storage"
      ]
    ],
    "header-max-length": [2, "always", 72],
    "body-max-line-length": [2, "always", 100],
    "subject-case": [2, "always", "lower-case"]
  }
}
```

#### 3. Тестирование правил через CLI
```bash
# Тест 1: Невалидный scope
echo "feat(unknown-mod): add service" | npx commitlint
# → ⧗   input: feat(unknown-mod): add service
# → ✖   scope must be one of [ansible, docker, helm, k8s, nginx, prometheus, grafana, systemd, ci, security, storage] [scope-enum]
# → ✖   found 1 problems, 0 warnings

# Тест 2: Заглавная буква в начале subject
echo "fix(nginx): Fix memory leak" | npx commitlint
# → ⧗   input: fix(nginx): Fix memory leak
# → ✖   subject must be lower-case [subject-case]
# → ✖   found 1 problems, 0 warnings

# Тест 3: Корректный инфраструктурный коммит
echo "feat(ansible): configure logrotate for systemd units" | npx commitlint
# → (код возврата 0, вывод пустой)
```

---

### Сценарий 4: Генерация CHANGELOG и тегов версий через git-cliff

`git-cliff` — автономный инструмент, парсящий историю Git-коммитов по шаблонам Tera и формирующий структурированный `CHANGELOG.md`.

#### 1. Установка бинарного файла (Linux x86_64)
```bash
# Загрузка и распаковка готового бинарника
curl -sL https://github.com/orhun/git-cliff/releases/download/v2.8.0/git-cliff-2.8.0-x86_64-unknown-linux-gnu.tar.gz | tar -xz
mv git-cliff-2.8.0/git-cliff /usr/local/bin/
git-cliff --version
# → git-cliff 2.8.0
```

#### 2. Конфигурация `cliff.toml` для SRE/DevOps репозитория
```toml
[changelog]
header = """
# Журнал изменений инфраструктуры\n
Все изменения документируются согласно спецификации Conventional Commits.\n
"""
body = """
{% if version %}\
    ## [{{ version | trim_start_matches(pat="v") }}] - {{ timestamp | date(format="%Y-%m-%d") }}
{% else %}\
    ## [Unreleased]
{% endif %}\
{% for group, commits in commits | group_by(attribute="group") %}
    ### {{ group | upper_first }}
    {% for commit in commits %}
        - {% if commit.scope %}**({{ commit.scope }})** {% endif %}{{ commit.message | upper_first }} ([{{ commit.id | truncate(length=7, end="") }}]({{ commit.id }}))\
    {% endfor %}
{% endfor %}
"""
trim = true

[git]
conventional_commits = true
filter_unconventional = true
commit_parsers = [
    { message = "^feat", group = "Новая функциональность (Features)" },
    { message = "^fix", group = "Исправления ошибок (Bug Fixes)" },
    { message = "^perf", group = "Производительность и тюнинг (Performance)" },
    { message = "^refactor", group = "Рефакторинг манифестов (Refactoring)" },
    { message = "^docs", group = "Документация и регламенты (Documentation)" },
    { message = "^ci", group = "CI/CD и пайплайны (Continuous Integration)" },
    { message = "^chore\\(deps\\)", group = "Обновление зависимостей (Dependencies)" },
    { message = "^chore", skip = true },
    { message = ".*", group = "Прочие изменения" },
]
```

#### 3. Генерация журнала изменений
```bash
# Предварительный просмотр следующей версии и невыпущенных изменений
git-cliff --bump --unreleased
# → ## [0.2.0] - 2026-10-11
# → ### Новая функциональность (Features)
# → - **(prometheus)** Add disk IOPS saturation alert rule (8a3f12c)
# → ### Исправления ошибок (Bug Fixes)
# → - **(k8s-ingress)** Increase memory limit to 512Mi to prevent OOM (4b9c10d)

# Запись в файл CHANGELOG.md
git-cliff --output CHANGELOG.md
# → CHANGELOG.md updated successfully
```

---

### Сценарий 5: Автоматизация релизов в On-Premise GitLab CI на базе semantic-release

В корпоративных средах без доступа к публичным облакам пайплайн автоматически анализирует историю ветки `main`, инкрементирует тег Git и создаёт релизную ветку.

Фрагмент `.gitlab-ci.yml`:

```yaml
stages:
  - lint
  - test
  - release

lint:commit-messages:
  stage: lint
  image: node:20-alpine
  script:
    - npm ci
    # Валидация всех коммитов ветки по сравнению с целевой
    - npx commitlint --from origin/$CI_MERGE_REQUEST_TARGET_BRANCH_NAME --to HEAD --verbose
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

release:automated:
  stage: release
  image: node:20-alpine
  before_script:
    - apk add --no-cache git
    - npm install -g semantic-release @semantic-release/gitlab @semantic-release/git @semantic-release/changelog
  script:
    - npx semantic-release
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
  variables:
    GITLAB_TOKEN: '$GITLAB_ACCESS_TOKEN'
```

Конфигурационный файл `.releaserc.json`:
```json
{
  "branches": ["main"],
  "plugins": [
    "@semantic-release/commit-analyzer",
    "@semantic-release/release-notes-generator",
    "@semantic-release/changelog",
    [
      "@semantic-release/git",
      {
        "assets": ["CHANGELOG.md"],
        "message": "chore(release): ${nextRelease.version} [skip ci]\n\n${nextRelease.notes}"
      }
    ],
    "@semantic-release/gitlab"
  ]
}
```

---

## Диагностика и устранение неполадок

| Проблема / Ошибка | Первопричина | Способ диагностики | Решение |
| :--- | :--- | :--- | :--- |
| `commit-msg hook rejected: invalid format` | Нарушен синтаксис Conventional Commits (пропущен двоеточие, пробел, заглавная буква, недопустимый тип) | Запустить валидацию вручную: `echo "$MSG" \| .git/hooks/commit-msg` | Исправить заголовок через `git commit --amend` с соблюдением формата `<type>(scope): description`. |
| `subject may not be empty [subject-empty]` | После двоеточия нет пробела или отсутствует текст описания | Проверить текст: `git log -1 --pretty=%B` | Добавить пробел и текст после двоеточия: `fix: add missing token`. |
| `scope must be one of [...] [scope-enum]` | Указан компонент, не входящий в разрешённый список конфигурации `commitlint` | Проверить список: `npx commitlint --print-config` | Использовать зарегистрированный scope либо расширить список в `.commitlintrc.json`. |
| `header-max-length` | Заголовок коммита превышает лимит (обычно 72 символа) | Посчитать символы: `head -n1 msg.txt \| wc -c` | Перенести детальные подробности в секцию `body`, сократив заголовок. |
| Пайплайн semantic-release завершился без создания релиза | В коммитах присутствовали только служебные типы (`chore`, `ci`, `docs`), не повышающие версию | Проверить лог CI: `Analysis of N commits resulted in no release` | Если в релиз должны войти изменения, добавить коммит типа `fix:` (для Patch) или `feat:` (для Minor). |
| Ошибки формата после Squash & Merge в веб-интерфейсе | Заголовок PR по умолчанию скопировал имя ветки или нестандартное имя вместо формата CC | Проверить коммит в целевой ветке: `git log -1 origin/main` | В настройках репозитория включить "Default PR title to PR title" и требовать conventional формат в заголовке Pull/Merge Request. |
| Случайный мажорный релиз (2.0.0 вместо 1.0.1) | В теле коммита случайно набрана строка `BREAKING CHANGE:` или поставлен знак `!` в `fix!:` | Проверить историю: `git log --grep="BREAKING CHANGE"` | При необходимости откатить тег или скорректировать commit message до слияния в основную ветку. |

### Исправление ошибочного коммита

#### 1. Исправление самого последнего локального коммита
```bash
# Исправление сообщения
git commit --amend -m "fix(nginx): correct buffer size for proxy pass"
# → [master e5d911a] fix(nginx): correct buffer size for proxy pass
```

#### 2. Пакетное исправление нескольких коммитов в ветке перед отправкой (rebase)
```bash
# Открытие интерактивного rebase для последних 3 коммитов
git rebase -i HEAD~3

# В открывшемся редакторе заменить 'pick' на 'reword' (или 'r') для коммитов с ошибками:
# r 7a1b2c3 fixed typo in config
# pick 8d2e3f4 test(ansible): add molecule test
# r 9c3f4e5 added new rule
#
# После сохранения Git поочерёдно запросит новые сообщения в формате Conventional Commits.
```

---

## Лучшие практики

1. **Атомарность каждого коммита**
   Один коммит должен отражать одно логическое действие. Не объединяйте правку Ansible-плейбука (`refactor(ansible)`) с обновлением конфигурации мониторинга (`feat(prometheus)`). Это позволяет генерировать точный changelog и безболезненно выполнять `git revert`.

2. **Строгое использование повелительного наклонения (Imperative Mood)**
   Пишите `feat: add metric exporter`, а не `feat: added metric exporter` или `feat: adds metric exporter`. Сообщение должно завершать фразу: *"If applied, this commit will..."*.

3. **Ограничение длины: правило 50/72**
   Заголовок не должен превышать 50–72 символов. Подробные обоснования, ссылки на логи сбоев и стек-трейсы переносите в `body`, разделяя строки переносом на 72 символах.

4. **Двухуровневый контроль (Local Hook + CI Gate)**
   Локальный `commit-msg` хук экономит время инженера, предотвращая создание невалидных коммитов до пуша. Однако хуки могут быть пропущены флагом `--no-verify`, поэтому этап линтинга коммитов в CI/CD пайплайне является обязательным контрольным рубежом.

5. **Стандартизация заголовков при Squash & Merge**
   Если команда использует стратегию Squash-Merge в GitLab/GitHub, критично форматировать заголовок самого Merge/Pull Request по стандарту Conventional Commits, так как именно он станет единственным коммитом в основной ветке.

6. **Использование Trailers для аудита и инцидент-менеджмента**
   В SRE связывайте коммиты с тикетами инцидентов и запросов на изменения через стандартные ключи в футере (`Fixes: #ID`, `Refs: INC-XXXX`, `Change-Id:`). Это позволяет автоматизированным системам формировать отчёты о закрытых инцидентах прямо из Git-истории.

---

## Дополнительная информация

### Связанные темы

- [Git Commit Template](./git_commit_template.md) — интерактивные шаблоны `.gitmessage`, конфигурация `commit.template` и интеграция с хуком `prepare-commit-msg`.
- [Git Hooks](./git_hooks.md) — архитектура клиентских и серверных хуков Git, автоматизация проверок.
- [Git Tags](./git_tags.md) — аннотированные теги Git, связь со спецификацией SemVer и релизными циклами.
- [Git Workflows](./git_workflows.md) — интеграция правил Conventional Commits в модели ветвления Trunk-Based Development и GitFlow.
- [Release Management](../Github_CI/Release_Management.md) — стратегии управления релизами и пайплайны автоматической публикации артефактов.

### Официальные ресурсы

- **Спецификация Conventional Commits v1.0.0:** [conventionalcommits.org](https://www.conventionalcommits.org/ru/v1.0.0/)
- **Спецификация Semantic Versioning (SemVer 2.0.0):** [semver.org](https://semver.org/lang/ru/)
- **Документация commitlint:** [commitlint.js.org](https://commitlint.js.org/)
- **Документация git-cliff:** [git-cliff.org](https://git-cliff.org/)
- **Документация semantic-release:** [semantic-release.github.io](https://semantic-release.github.io/)
