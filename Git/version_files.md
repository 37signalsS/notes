# Файлы версий — Version Files

**Актуально для:** mise 2026.10.x, asdf 0.20.x (с 0.16.0, 2025-01, asdf переписан на Go), актуальные релизы rustup, direnv, tfenv (проверено 2026-10)

## Определения

**Version Files** (файлы версий) — конфигурационные файлы, содержащие сведения о конкретной версии языка программирования, рантайма, библиотеки или системного инструмента, необходимых для работы проекта.

**Миссия:** Обеспечение идентичности рабочего окружения (Reproducible Environments) на машинах разработчиков, серверах сборки и в продакшене. Они решают проблему «работает только у меня» и автоматизируют переключение контекста при переходе между проектами.

**Reproducible Environment (Воспроизводимое окружение):** Состояние системы, при котором любой член команды, CI-сервер или новый экземпляр инфраструктуры может получить идентичный набор инструментов одинаковых версий, гарантируя предсказуемость сборки и деплоя.

**Environment Parity (Паритет окружений):** Принцип, при котором локальная среда разработчика максимально приближена к продакшену. Файлы версий являются первым шагом к паритету, фиксируя рантаймы и CLI-инструменты.

**Override (Переопределение):** Локальное изменение версии инструмента для конкретной директории без модификации глобального конфига. Может быть явным (через `.mise.local.toml` в mise) или неявным (через переменную окружения `MISE_NODE_VERSION`, `ASDF_NODEJS_VERSION`).

---

## Основные концепции

### Классификация файлов версий

#### 1. Специализированные (Mono-language)
Ориентированы на один конкретный стек. Обычно создаются и читаются специализированным менеджером версий:

- `.node-version` / `.nvmrc` — Node.js. Поддерживается `nvm`, `fnm`, `mise`, `asdf`. Формат: точная версия (`20.12.2`), частичная версия (`20` или `20.12` — последняя доступная из линейки) или алиас (`node`, `lts/*`, `lts/hydrogen`). semver-диапазоны `nvm` не поддерживает (в нём нет парсера semver); диапазоны умеет `mise`. `nvm` ищет `.nvmrc`, затем `.node-version`, поднимаясь по директориям; файл должен заканчиваться переводом строки.
- `.ruby-version` — Ruby (rbenv, rvm, mise, asdf).
- `.python-version` — Python (pyenv, uv, mise, asdf). Формат: точная версия (`3.12.3`) или `system` (в pyenv — системный интерпретатор).
- `.java-version` — Java (jenv, mise). Используется для переключения между JDK-дистрибутивами (Temurin/Adoptium, Oracle, Azul); команда `jenv local` записывает выбранную версию в этот файл.
- `.jenv-version` — устаревший файл jenv (до введения `.java-version`). Для обратной совместимости jenv его читает, но `.java-version` в той же директории имеет приоритет. Алиасы jenv кодируют дистрибутив и разрядность (например, `temurin64-21.0.2`).
- `rust-toolchain.toml` — Rust (rustup). Позволяет фиксировать не только версию, но и компоненты (clippy, rust-src, rustfmt), канал (`stable`, `beta`, `nightly`) и профиль (`minimal`, `complete`).
- `.sdkmanrc` — JVM-стек и инструменты сборки (Gradle, Maven, Spring Boot). Поддерживается `sdkman`.
- `go.mod` — хотя это файл зависимостей, директива `go 1.x` используется инструментами (`g`, `goenv`) для выбора рантайма.
- `.php-version` — PHP (phpbrew, mise, asdf).
- `.perl-version` — Perl (perlbrew, mise, asdf).
- `.haskell-version` — Haskell (ghcup, mise, asdf).
- `.swift-version` — Swift (swiftenv, mise).
- `.erlang-version` — Erlang (kerl, asdf).
- `.config/dotnet-tools.json` — .NET CLI local tools. Манифест локальных инструментов (создаётся командой `dotnet new tool-manifest`, устанавливается `dotnet tool install` без `--global`, восстанавливается `dotnet tool restore`). Глобальные инструменты (`~/.dotnet/tools`, per-user) манифеста не имеют.
- `.terraform-version` — Terraform (tfenv, mise). Формат tfenv: точная версия (`1.8.5`), `latest`, `latest:<regex>`, `latest-allowed` / `min-required` (разрешают версию по `required_version` из `.tf`-файлов). tfenv не парсит semver-диапазоны; диапазоны (`>= 1.8, < 2.0`) поддерживает mise.
- `.lua-version` — Lua (luaver, mise, asdf).

#### 2. Универсальные (Polyglot / Modern)
Управляют всем стеком проекта в одном месте. Используются многоязычными менеджерами:

- `.tool-versions` — стандарт, введенный `asdf`, поддерживаемый `mise`. Формат: `tool version` (по одному инструменту на строку).
- `.mise.toml` — расширенный формат для `mise` (также читается как `mise.toml`, `mise/config.toml`, `.mise/config.toml`, `.config/mise.toml`). Поддерживает диапазоны версий, переменные окружения (`[env]`) и задачи (`[tasks]`, в том числе условные через `if`). Личные некоммитируемые переопределения — в `.mise.local.toml`.
- `.rtx.toml` — устаревшее название конфига (проект `rtx` → `mise`, 2024). Поддержка объявлена deprecated и в списке конфигов актуальных версий mise отсутствует — переименуйте в `mise.toml`.
- `.envrc` — файл для `direnv`. Позволяет загружать не только переменные, но и активировать окружения через хуки (например, `use flake` для Nix, `layout python` для виртуальных окружений).
- `direnvrc` — глобальный конфиг `direnv` в `~/.config/direnv/direnvrc` (или `$XDG_CONFIG_HOME/direnv/direnvrc`). Bash-код, загружаемый перед каждым `.envrc`: пользовательские функции `layout_*` и расширения stdlib. Дополнительно подгружаются файлы `~/.config/direnv/lib/*.sh`; настройки самого `direnv` — в `direnv.toml`.

### Сравнение менеджеров версий

| Инструмент | Языки | Файлы | Особенности |
| :--- | :--- | :--- | :--- |
| **asdf** | Все (плагины) | `.tool-versions` | Стандарт индустрии, огромная база плагинов. С 0.16.0 (2025-01) переписан на Go: один бинарник, 2–20x быстрее Bash-версии; плагины остались на Bash. |
| **mise** | Все | `.mise.toml`, `.tool-versions` | На Rust (очень быстрый), встроенный task runner, заменяет direnv. `.rtx.toml` — deprecated, в актуальных версиях не читается. |
| **nvm / fnm** | Node.js | `.nvmrc`, `.node-version` | Узкая специализация, высокая стабильность. `fnm` написан на Rust и работает быстрее `nvm`. |
| **pyenv / uv** | Python | `.python-version` | `pyenv` компилирует Python из исходников (медленно); `uv` скачивает бинарники (быстро) и заменяет `pip`, `pipx`, `venv`. |
| **rustup** | Rust | `rust-toolchain.toml` | Официальный инструмент, глубокая интеграция с cargo. Поддерживает override в поддиректориях. |
| **jenv** | Java | `.java-version` | Управляет версиями JDK; алиасы кодируют дистрибутив и разрядность (например, `temurin64-21.0.2`). |
| **sdkman** | JVM / Build | `.sdkmanrc` | Менеджер для JVM-языков и инструментов сборки (Gradle, Maven, Kotlin, Groovy). Только Unix. |
| **direnv** | Все (окружение) | `.envrc` | Не управляет версиями напрямую, но активирует окружение при входе в директорию. Может вызывать `mise` или `asdf` внутри себя. |
| **g** | Go | `go.mod` | Менеджер Go без собственного файла версий: автоматическое переключение по директиве `go` в `go.mod`, иначе через CLI (`g use 1.19.10`). |
| **tfenv** | Terraform | `.terraform-version` | Специализированный менеджер для Terraform. Форматы `latest`, `latest:<regex>`, `latest-allowed`, `min-required` (без semver-диапазонов). |

### Механизм работы: Шиммы (Shims) vs Динамический PATH

Большинство менеджеров используют один из двух подходов для перехвата вызова команды:

#### 1. Шиммы (Shims)
Создание "прослоек" в директории, которая всегда находится в `PATH`. Шим анализирует текущую папку и вызывает нужный бинарный файл.

**Принцип работы:**
1. Пользователь вводит команду `terraform`.
2. Оболочка ищет исполняемый файл в директориях `PATH`, начиная с первой.
3. Первым находится "шим" `~/.local/share/mise/shims/terraform` (или `~/.asdf/shims/terraform`).
4. Шим читает конфигурационный файл (`.mise.toml` или `.tool-versions`) в текущей директории и её родителях.
5. Шим определяет нужную версию и передает выполнение реальному бинарному файлу.

**Пример для `nvm` (специфика Node.js):**
```bash
# nvm не использует классические шимы, а перехватывает команду через shell-функцию
# При вызове node/npm/npx функция nvm ищет .nvmrc и вызывает нужную версию
nvm use 20.12.2
node -v  # → v20.12.2
```

**Пример для `pyenv` (Python):**
```bash
# pyenv создает шимы в ~/.pyenv/shims/
~/.pyenv/shims/python -> .../pyenv-version-from-file
# При вызове шим читает .python-version и вызывает нужный интерпретатор
python -V  # → Python 3.12.3
```

#### 2. Динамический PATH
Инструмент перехватывает событие смены директории в shell и динамически модифицирует переменную `PATH`.

**Пример для `mise` (shell activation):**
```bash
# В ~/.zshrc
eval "$(mise activate zsh)"

# При входе в директорию с .mise.toml mise добавляет путь к нужной версии в начало PATH
# Шим в ~/.local/share/mise/shims/ все равно существует, но теперь PATH модифицируется
echo $PATH  # → ~/.local/share/mise/installs/terraform/1.8.4/bin:...
```

**Пример для `direnv`:**
```bash
# В ~/.bashrc
eval "$(direnv hook bash)"

# При входе в директорию direnv анализирует .envrc
# Если .envrc содержит "layout python", direnv добавляет .venv/bin в PATH
# Если содержит "use flake", direnv активирует Nix-окружение
```

---

## Практические сценарии

### Сценарий 1: Автоматизация с .tool-versions (asdf/mise)
Идеально для Fullstack-проектов. Подходит, когда команда использует разные языки и инструменты.

**Предварительные требования:**
- Установленный `asdf` или `mise` с соответствующими плагинами.
- Оболочка (bash/zsh/fish) с активированным менеджером версий.
- Права на запись в корне проекта (для создания файла).

**Шаг 1: Создание файла**
```bash
cat > .tool-versions << 'EOF'
nodejs 20.12.2
python 3.12.3
terraform 1.8.5
kubectl 1.30.0
EOF
```

**Шаг 2: Установка инструментов**
```bash
# asdf
asdf install

# mise
mise install
# → installing nodejs-20.12.2
# → installing python-3.12.3
# → installing terraform-1.8.5
# → installing kubectl-1.30.0
```

**Шаг 3: Проверка активации**
```bash
# При входе в директорию
cd /path/to/project
node -v  # → v20.12.2
python -V  # → Python 3.12.3
terraform -version  # → Terraform v1.8.5
kubectl version --client  # → Client Version: v1.30.0
```

**Валидация:**
```bash
# Проверить, что активные версии совпадают с файлом
# mise
mise current
# → nodejs 20.12.2
# → python 3.12.3
# → terraform 1.8.5
# → kubectl 1.30.0

# asdf (0.16+: вывод в 4 колонки — инструмент, версия, источник, установлен)
asdf current
# → nodejs 20.12.2 /path/to/project/.tool-versions true
# → python 3.12.3 /path/to/project/.tool-versions true
```

### Сценарий 2: Расширенный конфиг с .mise.toml (задачи, env, диапазоны)
Подходит для проектов, где нужно не только фиксировать версии, но и автоматизировать рутинные операции.

**Предварительные требования:**
- Установленный `mise` (Calver-версии, 2024+).
- Оболочка с активацией `mise`.

**Шаг 1: Создание .mise.toml**
```toml
# .mise.toml
[tools]
nodejs = "20.12.2"
python = "3.12.3"
terraform = "1.8.5"
kubectl = "1.30.0"
helm = "3.14.4"
jq = "1.7.1"
yq = "4.44.1"

[env]
# Переменные окружения, экспортируемые при входе в директорию
TF_VAR_environment = "production"
ANSIBLE_HOST_KEY_CHECKING = "False"

[tasks]
# Задачи могут вызывать любые команды, включая версионированные инструменты
[tasks.tf-lint]
description = "Форматирует и валидирует Terraform код"
run = [
  "terraform fmt -recursive",
  "terraform validate",
]

[tasks.tf-plan]
description = "Создает план изменений Terraform"
run = "terraform plan -out=tfplan"
dir = "infrastructure/production/"

[tasks.ci-test]
description = "Задача для CI"
depends_on = ["tf-lint"]
run = "echo 'CI tests passed!'"
```

**Шаг 2: Выполнение задач**
```bash
# Список доступных задач
mise tasks
# → tf-lint  Форматирует и валидирует Terraform код
# → tf-plan  Создает план изменений Terraform
# → ci-test  Задача для CI

# Запуск задачи
mise run tf-lint
# → terraform fmt -recursive
# → terraform validate
# → Success! The configuration is valid.

# Проверка версий
mise which terraform
# → ~/.local/share/mise/installs/terraform/1.8.5/bin/terraform
```

**Валидация:**
```bash
# Проверить экспорт переменных окружения
env | grep TF_VAR
# → TF_VAR_environment=production

# Проверить версии инструментов
mise current
# → nodejs 20.12.2
# → python 3.12.3
# → terraform 1.8.5
```

### Сценарий 3: Безопасность и "доверие" (Trust)
Версионные файлы могут выполнять произвольный код (особенно `.envrc` или `.mise.toml` с задачами).

**Правила безопасности:**

**mise:**
```bash
# При первом входе mise запрашивает доверие интерактивно.
# Без терминала (editor, CI) команда завершается ошибкой:
# error: Config files in /path/to/project are not trusted

# Если вы доверяете файлу:
mise trust .mise.toml

# Статус доверия для текущей директории и всех родительских:
mise trust --show

# Отозвать явное доверие (если файл был изменён без вашего ведома):
mise trust --untrust .mise.toml

# Пропустить файл и игнорировать его впредь:
mise trust --ignore .mise.toml
```

> **Нюанс:** конфиг, содержащий только `min_version`, записи `[tools]` с простыми версиями и `[tasks]` без `secrets`, доверия не требует (кроме paranoid mode). Команды `mise run`, `mise exec` и шорткаты задач доверяют активный конфиг автоматически.

**direnv:**
```bash
# При первом входе в директорию с .envrc direnv заблокирует активацию
# Вывод:
# direnv: error /path/to/project/.envrc is blocked. Run `direnv allow` to approve its content.

# Разрешить активацию (после проверки содержимого .envrc)
direnv allow

# Отозвать разрешение (если .envrc был изменен)
direnv deny
```

**Варианты атак через версионные файлы:**
1. **Exfiltration данных:** `.envrc` может читать файлы и отправлять их на внешний сервер через `curl`.
2. **Установка вредоносного ПО:** Задача в `.mise.toml` может выполнить `curl | bash`.
3. **Кража секретов:** Переменные окружения (включая `AWS_SECRET_ACCESS_KEY`) экспортируются и могут быть логированы.

**Меры защиты:**
- Никогда не выполняйте `mise trust` или `direnv allow` для файлов из непроверенных источников (форки, внешние PR).
- Используйте `mise trust --untrust` при получении уведомления об изменении файла.
- Для CI используйте `mise` без задач (только `[tools]`), чтобы исключить выполнение произвольного кода.
- В `.mise.toml` избегайте задач, выполняющих `curl`, `wget`, `git clone` из непроверенных источников.

### Сценарий 4: Использование в контейнерах
Файлы версий — отличный источник метаданных для Docker, гарантирующий, что образ собран с тем же стеком, что и локальная разработка.

**Dockerfile с использованием `.node-version`:**

```dockerfile
# Dockerfile
# Командная подстановка $(cat ...) в директиве FROM недопустима —
# версию передаём через ARG и --build-arg
ARG NODE_VERSION=20.12.2
FROM node:${NODE_VERSION}-slim AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production

COPY . .
RUN npm run build

FROM node:${NODE_VERSION}-slim
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
CMD ["node", "dist/main.js"]
```

**Валидация:**
```bash
# Собрать образ, подставив версию из файла
docker build --build-arg NODE_VERSION="$(cat .node-version)" -t myapp:$(cat .node-version) .
# → #1 [internal] load build definition from Dockerfile
# → #3 [internal] load metadata for docker.io/library/node:20.12.2-slim

# Запустить и проверить версию Node внутри контейнера
docker run --rm myapp:$(cat .node-version) node -v
# → v20.12.2
```

**Dockerfile с использованием `.mise.toml` (multi-stage):**

```dockerfile
# Этап 1: сборка с точными версиями инструментов из .mise.toml
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl https://mise.jdx.dev/install.sh | sh
ENV PATH="/root/.local/share/mise/shims:${PATH}"

WORKDIR /app
COPY .mise.toml ./
RUN mise install          # устанавливает точные версии из [tools]

COPY . .
RUN python -m build       # реальная сборка проекта

# Этап 2: финальный образ
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app/dist ./dist
# При необходимости перенести конкретный инструмент из mise:
# COPY --from=builder /root/.local/share/mise/installs/yq/4.44.1/bin/yq /usr/local/bin/
CMD ["python3.12", "dist/main.py"]
```

### Сценарий 5: Интеграция с CI/CD (GitHub Actions)
Файлы версий позволяют избежать дублирования версий между локальным конфигом и CI-пайплайном.

**GitHub Actions с `mise-action`:**

```yaml
# .github/workflows/ci.yml
name: CI for Infrastructure

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup mise
        uses: jdx/mise-action@v2
        # Автоматически читает .mise.toml и устанавливает инструменты

      - name: Verify versions
        run: |
          terraform version
          ansible --version
          python --version

      - name: Run Terraform Lint
        run: mise run tf-lint

      - name: Run CI Tests
        run: mise run ci-test
```

**GitHub Actions с `asdf`:**

```yaml
# .github/workflows/ci.yml
name: CI with asdf

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # v4 — актуальная мажорная версия action; устанавливает asdf и
      # инструменты из закоммиченного .tool-versions (вход tool_versions
      # нужен только если файла нет в репозитории — это содержимое файла, а не путь)
      - name: Setup asdf
        uses: asdf-vm/actions/install@v4

      - name: Run tests
        run: |
          node -e "console.log(process.version)"
          python -c "import sys; print(sys.version)"
```

**GitLab CI с `mise`:**

```yaml
# .gitlab-ci.yml
image: python:3.12

before_script:
  - curl https://mise.jdx.dev/install.sh | sh
  - eval "$(/root/.local/bin/mise activate bash)"
  - mise install

test:
  script:
    - mise run ci-test
```

**Валидация CI:**
```bash
# Логи CI должны содержать строки типа:
# → Installing nodejs-20.12.2
# → terraform fmt -recursive
# → Success! The configuration is valid.
```

### Сценарий 6: Локальные переопределения
Иногда разработчику нужно временно использовать другую версию инструмента для отладки, не меняя общий конфиг.

> **Важно:** файла `.tool-versions.local` не существует — ни asdf, ни mise его не читают. Локальные переопределения делаются через `.mise.local.toml` (mise), переменные окружения или команду записи версии в проектный файл.

**Способы переопределения (по приоритету, от высшего к низшему):**

1. **Переменная окружения (самый высокий приоритет):**
```bash
# Переопределить версию Node для одной команды (mise)
MISE_NODE_VERSION=18.20.0 node -v  # → v18.20.0

# Аналоги для других менеджеров:
# ASDF_NODEJS_VERSION=18.20.0 ...   (asdf)
# TFENV_TERRAFORM_VERSION=1.8.5 ... (tfenv)
# JENV_VERSION=21.0.2 ...           (jenv)
```

2. **Локальный некоммитируемый файл (mise):**
```bash
# Личные версии — в .mise.local.toml (должен быть в .gitignore)
mise use --env local node@18.20.0
# → записывает nodejs = "18.20.0" в .mise.local.toml

# Проверить
mise current nodejs
# → nodejs 18.20.0 (set by .mise.local.toml)
```
`mise use node@18.20.0` без `--env local` пишет в ближайший общий конфиг (обычно `.mise.toml`) — коммите этот файл только если версия общая для команды.

**direnv:** локальные переопределения через `.envrc.local` — добавьте в `.envrc` строку `source_env_if_exists .envrc.local` и игнорируйте `.envrc.local` в git.

3. **Запись версии в проектный файл (asdf):**
```bash
# asdf 0.16+ (Go): команды asdf local/asdf global заменены на asdf set
asdf set nodejs 18.20.0

# Проверить
asdf current nodejs
# → nodejs 18.20.0 /path/to/project/.tool-versions true
```
Для asdf <0.16 (Bash) команда `asdf local nodejs 18.20.0` работает как раньше. Обходной путь для изолированного файла в asdf — переменная `ASDF_DEFAULT_TOOL_VERSIONS_FILENAME`.

**asdf без своего локального файла:** у asdf нет нативного аналога `.mise.local.toml`; `asdf set` пишет прямо в `.tool-versions` текущей директории.

### Сценарий 7: Совмещение с Nix (flake.nix)
Современный подход к абсолютно воспроизводимым средам. Может сосуществовать с `mise` через интеграцию в `.envrc`.

```nix
# flake.nix
{
  description = "My project dev environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { nixpkgs, ... }:
    let
      pkgs = import nixpkgs { system = "x86_64-darwin"; };
    in {
      devShells.x86_64-darwin.default = pkgs.mkShell {
        buildInputs = with pkgs; [
          nodejs_20
          python312
          terraform_1_8
        ];
      };
    };
}
```

```bash
# .envrc
use flake

# При входе в директорию direnv активирует Nix-окружение
# Если требуется одновременно использовать mise, можно вызвать его внутри flake
```

---

## Устранение неисправностей (Troubleshooting)

### Проблема 1: Версия инструмента не переключается
**Симптом:** При переходе в директорию проекта версия инструмента остается старой.

**Диагностика:**
```bash
# Проверить, что менеджер версий активен
which terraform
# → ~/.local/share/mise/shims/terraform  (mise)
# → ~/.asdf/shims/terraform              (asdf)
# → /usr/local/bin/terraform             (не используется менеджер)

# Проверить конфигурационный файл
ls -la .tool-versions .mise.toml .mise.local.toml .python-version .nvmrc

# Проверить вывод текущих версий
mise current
asdf current
pyenv version
nvm current
```

**Решение:**
```bash
# mise
mise trust .mise.toml  # Если файл не доверен
mise install           # Если инструмент не установлен

# asdf
asdf install           # Если инструмент не установлен

# pyenv
pyenv install 3.12.3   # Если интерпретатор не установлен
pyenv local 3.12.3     # Установить локальную версию

# nvm
nvm use                # Использовать версию из .nvmrc
```

### Проблема 2: "Mangled PATH" или "Shim not found"
**Симптом:** Команда инструмента не найдена, хотя менеджер версий установлен.

**Диагностика:**
```bash
# Проверить переменную PATH
echo $PATH | tr ':' '\n' | head -10
# Должен содержать ~/.local/share/mise/shims или ~/.asdf/shims в начале

# Проверить наличие шимов
ls -la ~/.local/share/mise/shims/terraform
ls -la ~/.asdf/shims/terraform
```

**Решение:**
```bash
# Перезапустить активацию оболочки
# Для zsh:
source ~/.zshrc
# Для bash:
source ~/.bashrc

# Или перезапустить терминал
```

### Проблема 3: "Permission denied" при установке инструментов
**Симптом:** Менеджер версий не может скачать или установить инструмент.

**Диагностика:**
```bash
# Проверить права на директорию установок
ls -la ~/.local/share/mise/installs/
ls -la ~/.pyenv/versions/
```

**Решение:**
```bash
# Исправить права (не используйте sudo внутри директории пользователя!)
chmod -R u+rw ~/.local/share/mise/installs/
chmod -R u+rw ~/.pyenv/versions/
```

### Проблема 4: Несовместимость версий в CI
**Симптом:** Сборка проходит локально, но падает в CI с ошибкой "version not found".

**Диагностика:**
```bash
# Убедиться, что файл версий закоммичен в репозиторий
git ls-files | grep -E 'version|tool-versions|mise.toml|nvmrc'

# Проверить, что CI-агент использует правильный runner
# GitHub Actions: ubuntu-latest может менять версию Ubuntu
```

**Решение:**
- Зафиксировать версию runner в CI (`runs-on: ubuntu-22.04`).
- Пинить версии CI-шагов полным SHA коммита (`actions/checkout@<полный-sha>`) вместо плавающего тега (`@v4`) — защита от подмены тега.
- Добавить шаг верификации версий в пайплайн.

### Проблема 5: `asdf local: command not found` после обновления
**Симптом:** после обновления asdf до 0.16+ команды `asdf local` и `asdf global` не найдены.

**Причина:** asdf 0.16.0 (2025-01) — полный рерайт на Go; `asdf local` и `asdf global` заменены на `asdf set`. Вывод `asdf current` тоже изменился (4 колонки вместо 3).

**Решение:**
```bash
# Было (asdf < 0.16):              Стало (asdf 0.16+):
# asdf local nodejs 20.12.2        → asdf set nodejs 20.12.2        (в .tool-versions текущей директории)
# asdf global nodejs 20.12.2       → asdf set --home nodejs 20.12.2  (в домашнем .tool-versions)
# asdf shell nodejs 20.12.2        → ASDF_NODEJS_VERSION=20.12.2 ...  (переменная в текущем шелле)
```
Другие ломающие изменения 0.16: дефисные команды убраны (`asdf list-all` → `asdf list all`, `asdf plugin-add` → `asdf plugin add`), команда `asdf update` удалена (обновление — только через пакетный менеджер ОС или ручную замену бинарника). Инструкция по миграции: [asdf-vm.com/guide/upgrading-to-v0-16](https://asdf-vm.com/guide/upgrading-to-v0-16.html).

---

## Рекомендации и ограничения

### Белые пятна и рекомендации

- **Git и .gitignore:** Файлы версий **ОБЯЗАТЕЛЬНО** должны быть в репозитории. В `.gitignore` попадают только локальные переопределения:
```gitignore
# Локальные переопределения — игнорируем
.mise.local.toml
.envrc.local
.python-version.local
.terraform-version.local
```
Коммитируемые файлы (`.tool-versions`, `.mise.toml`, `.envrc`, `rust-toolchain.toml`, `.config/dotnet-tools.json`) в `.gitignore` попадать не должны — строка с таким именем в `.gitignore` проигнорирует файл целиком.
- **Ключевое слово `latest`:** не используйте `latest` в `.tool-versions` — `asdf install` не умеет его разрешать в файле (работает только в аргументах командной строки). Фиксируйте точные версии, иначе воспроизводимость окружения теряется.
- **Nix (flake.nix):** Современный подход к абсолютно воспроизводимым средам. Может сосуществовать с `mise` через интеграцию в `.envrc`. При использовании Nix файлы версий могут дублировать конфигурацию — выбирайте один источник истины.
- **Devcontainers:** Файл `devcontainer.json` часто дополняет файлы версий, описывая не только рантайм, но и расширения IDE и системные зависимости. DevContainer может использовать файлы версий через `postCreateCommand`.
- **Corepack (Node.js):** Современная альтернатива `nvm` для управления версиями `npm`, `yarn`, `pnpm`. Использует `package.json` поле `"packageManager"` и не требует отдельного файла версий.
- **Poetry / PDM (Python):** Менеджеры зависимостей, которые также управляют версиями интерпретатора через `pyproject.toml` поле `requires-python`. Могут заменять `.python-version` в проектах, где требуется строгая воспроизводимость через lock-файлы.

### Известные ограничения

- **Медленная компиляция pyenv:** Компиляция Python из исходников может занимать 5–15 минут. Используйте `pyenv install --list` для проверки доступных версий и `uv` для быстрого скачивания бинарников.
- **Плагины asdf:** Не все плагины поддерживают все ОС (macOS, Linux, WSL). Перед добавлением инструмента проверьте совместимость плагина.
- **Windows:** `pyenv` и `asdf` (плагины — Bash-скрипты) не работают на Windows нативно — используйте `pyenv-win`, `nvm-windows`, `scoop` или WSL2. `mise` работает на Windows нативно (`winget install jdx.mise`), но инструменты из asdf-плагинов на ней не запускаются — только core-бэкенды (`aqua`, `github`, `http`, `npm`, `vfox`) и сами Windows-совместимые инструменты.
- **Версии в lock-файлах:** Файлы версий управляют версиями инструментов, но не гарантируют идентичность зависимостей. Для этого требуются lock-файлы (`package-lock.json`, `poetry.lock`, `Cargo.lock`, `go.sum`).

### Процедура миграции между менеджерами

При переходе с одного менеджера на другой:

```bash
# 1. Экспорт текущих версий (для сверки)
asdf current > asdf-versions.txt
mise current > mise-versions.txt

# 2. Установка нового менеджера
curl https://mise.jdx.dev/install.sh | sh

# 3. Перенос конфигурации
# mise нативно читает .tool-versions — конвертация не требуется.
# При желании переписать конфиг вручную в .mise.toml (TOML-синтаксис,
# формат несовместим побайтово — cp .tool-versions .mise.toml некорректен):
#   [tools]
#   nodejs = "20.12.2"

# 4. Верификация
mise install
mise current
```

> **Миграция asdf 0.15 → 0.16+:** см. раздел «Проблема 5» и [upgrading-to-v0-16](https://asdf-vm.com/guide/upgrading-to-v0-16.html) — меняется не только менеджер, но и синтаксис команд.

---

## Связанные темы

- [mise.md](../mise.md) — детальное руководство по самому мощному менеджеру версий.
- [Обзор специальных файлов Git](./git_special_files_overview.md) — классификация служебных файлов.
- [Управление версиями Python](../Linux/Development/python_management.md) — специфика `pyenv` и `uv`.
- [EditorConfig](./editorconfig.md) — стандартизация форматирования кода.
- [Git Hooks — pre-commit](./git_hooks.md) — автоматизация проверок перед коммитом.
- [Dockerfile: Лучшие практики для Rust](../Docker/Dockerfile/Docker_best_practices/rust.md) — использование `rust-toolchain.toml` в контейнерах.

### Официальные ресурсы

- [mise documentation](https://mise.jdx.dev/)
- [asdf-vm guide](https://asdf-vm.com/)
- [asdf upgrade guide 0.16 (Go rewrite)](https://asdf-vm.com/guide/upgrading-to-v0-16.html)
- [rustup specification](https://rust-lang.github.io/rustup/overrides.html#the-toolchain-file)
- [direnv manual](https://direnv.net/)
- [nvm GitHub](https://github.com/nvm-sh/nvm)
- [pyenv GitHub](https://github.com/pyenv/pyenv)
- [tfenv GitHub](https://github.com/tfutils/tfenv)
