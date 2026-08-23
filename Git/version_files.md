# Файлы версий — Version Files

## Определения

**Version Files** (файлы версий) — конфигурационные файлы, содержащие сведения о конкретной версии языка программирования, рантайма, библиотеки или системного инструмента, необходимых для работы проекта.

**Миссия:** Обеспечение идентичности рабочего окружения (Reproducible Environments) на машинах разработчиков, серверах сборки и в продакшене. Они решают проблему «работает только у меня» и автоматизируют переключение контекста при переходе между проектами.

**Reproducible Environment (Воспроизводимое окружение):** Состояние системы, при котором любой член команды, CI-сервер или новый экземпляр инфраструктуры может получить идентичный набор инструментов одинаковых версий, гарантируя предсказуемость сборки и деплоя.

**Environment Parity (Паритет окружений):** Принцип, при котором локальная среда разработчика максимально приближена к продакшену. Файлы версий являются первым шагом к паритету, фиксируя рантаймы и CLI-инструменты.

**Override (Переопределение):** Локальное изменение версии инструмента для конкретной директории без модификации глобального конфига. Может быть явным (через `.tool-versions.local`) или неявным (через переменную окружения `MISE_NODE_VERSION`).

---

## Основные концепции

### Классификация файлов версий

#### 1. Специализированные (Mono-language)
Ориентированы на один конкретный стек. Обычно создаются и читаются специализированным менеджером версий:

- `.node-version` / `.nvmrc` — Node.js. Поддерживается `nvm`, `fnm`, `mise`, `asdf`. Формат: строка с версией (например, `20.12.2`) или диапазон (`lts/*`).
- `.ruby-version` — Ruby (rbenv, rvm, mise, asdf).
- `.python-version` — Python (pyenv, uv, mise, asdf). Формат: точная версия (`3.12.3`) или алиас (`latest`, `system`).
- `.java-version` — Java (jenv, mise). Используется для переключения между JDK-дистрибутивами (Adoptium, Oracle, Azul).
- `.jenv-version` — Java (jenv). В отличие от `.java-version`, позволяет задавать точный путь к JDK или использовать 32-битную версию.
- `rust-toolchain.toml` — Rust (rustup). Позволяет фиксировать не только версию, но и компоненты (clippy, rust-src, rustfmt), канал (`stable`, `beta`, `nightly`) и профиль (`minimal`, `complete`).
- `.sdkmanrc` — JVM-стек и инструменты сборки (Gradle, Maven, Spring Boot). Поддерживается `sdkman`.
- `go.mod` — хотя это файл зависимостей, директива `go 1.x` используется инструментами (`g`, `goenv`) для выбора рантайма.
- `.php-version` — PHP (phpbrew, mise, asdf).
- `.perl-version` — Perl (perlbrew, mise, asdf).
- `.haskell-version` — Haskell (ghcup, mise, asdf).
- `.swift-version` — Swift (swiftenv, mise).
- `.erlang-version` — Erlang (kerl, asdf).
- `.dotnet-tools.json` — .NET CLI tools (`dotnet tool`). Хранит версии глобальных инструментов (например, `dotnet-ef`, `paket`).
- `.terraform-version` — Terraform (tfenv, mise). Поддерживает диапазоны (`>= 1.8, < 2.0`).
- `.lua-version` — Lua (luaver, mise, asdf).
- `.nodeenv` — Python-пакет, но иногда используется как маркер версии Node в проектах.

#### 2. Универсальные (Polyglot / Modern)
Управляют всем стеком проекта в одном месте. Используются многоязычными менеджерами:

- `.tool-versions` — стандарт, введенный `asdf`, поддерживаемый `mise`. Формат: `tool version` (по одному инструменту на строку).
- `.mise.toml` — расширенный формат для `mise`. Поддерживает диапазоны версий, переменные окружения (`[env]`) и задачи (`[tasks]`). TOML-синтаксис позволяет задавать условные конфигурации через `if`.
- `.rtx.toml` — устаревшее название для `.mise.toml` (до переименования проекта `rtx` → `mise`). Обратная совместимость сохраняется.
- `.envrc` — файл для `direnv`. Позволяет загружать не только переменные, но и активировать окружения через хуки (например, `use flake` для Nix, `layout python` для виртуальных окружений).
- `.direnvrc` — глобальный конфиг `direnv` в `~/.config/direnv/`. Определяет пользовательские функции `layout_*` и глобальные правила безопасности.

### Сравнение менеджеров версий

| Инструмент | Языки | Файлы | Особенности |
| :--- | :--- | :--- | :--- |
| **asdf** | Все (плагины) | `.tool-versions` | Стандарт индустрии, огромная база плагинов. Медленные шимы на Bash. |
| **mise** | Все | `.mise.toml`, `.tool-versions` | На Rust (очень быстрый), встроенный task runner, заменяет direnv, обратная совместимость с `.rtx.toml`. |
| **nvm / fnm** | Node.js | `.nvmrc`, `.node-version` | Узкая специализация, высокая стабильность. `fnm` написан на Rust и работает быстрее `nvm`. |
| **pyenv / uv** | Python | `.python-version` | `pyenv` компилирует Python из исходников (медленно); `uv` скачивает бинарники (быстро) и заменяет `pip`, `pipx`, `venv`. |
| **rustup** | Rust | `rust-toolchain.toml` | Официальный инструмент, глубокая интеграция с cargo. Поддерживает override в поддиректориях. |
| **jenv** | Java | `.java-version`, `.jenv-version` | Управляет версиями JDK. Поддерживает 32-битные архитектуры и разные дистрибутивы. |
| **sdkman** | JVM / Build | `.sdkmanrc` | Менеджер для JVM-языков и инструментов сборки (Gradle, Maven, Kotlin, Groovy). Только Unix. |
| **direnv** | Все (окружение) | `.envrc` | Не управляет версиями напрямую, но активирует окружение при входе в директорию. Может вызывать `mise` или `asdf` внутри себя. |
| **fnm** | Node.js | `.nvmrc`, `.node-version` | Быстрая альтернатива `nvm` на Rust. Поддерживает `.node-version` и `.nvmrc`. |
| **g** | Go | `(отсутствует)` | Менеджер версий Go без файла версий — работает через аргументы командной строки. |
| **tfenv** | Terraform | `.terraform-version` | Специализированный менеджер для Terraform. Поддерживает диапазоны версий. |

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

# asdf
asdf current
# → nodejs 20.12.2 (set by /path/to/project/.tool-versions)
# → python 3.12.3 (set by /path/to/project/.tool-versions)
```

### Сценарий 2: Расширенный конфиг с .mise.toml (задачи, env, диапазоны)
Подходит для проектов, где нужно не только фиксировать версии, но и автоматизировать рутинные операции.

**Предварительные требования:**
- Установленный `mise` (версия 2024+).
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
# → ~/.local/share/mise/installs/terraform/1.8.4/bin/terraform
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
# При изменении .mise.toml или первом входе инструмент запросит подтверждение
# Если вы доверяете файлу:
mise trust .mise.toml

# Если файл из непроверенного источника — НЕ ВЫПОЛНЯЙТЕ trust
# Команда mise с новым недоверенным .mise.toml:
mise x python -- python -c "print('ok')"
# → error: .mise.toml is not trusted. Run `mise trust .mise.toml` to trust it.

# Отозвать доверие (если файл был изменен без вашего ведома)
mise trust --untrust .mise.toml
```

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
FROM node:$(cat .node-version)-slim AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production

COPY . .
RUN npm run build

FROM node:$(cat .node-version)-slim
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
CMD ["node", "dist/main.js"]
```

**Валидация:**
```bash
# Собрать образ
docker build -t myapp:$(cat .node-version) .
# → Step 1/6 : FROM node:20.12.2-slim AS builder
# → 20.12.2-slim: Pulling from library/node

# Запустить и проверить версию Node внутри контейнера
docker run --rm myapp:$(cat .node-version) node -v
# → v20.12.2
```

**Dockerfile с использованием `.mise.toml` (multi-stage):**

```dockerfile
# Этап 1: Сборка с помощью mise
FROM python:3.12-slim AS builder

# Установка mise
RUN pip install mise

# Копируем файлы версий
COPY .tool-versions .mise.toml ./
RUN mise install

# Этап 2: Финальный образ
FROM python:3.12-slim
COPY --from=builder /root/.local/share/mise/installs/python/3.12.3/bin/python3.12 /usr/local/bin/python3.12
COPY --from=builder /app/dist ./dist
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

      - name: Setup asdf
        uses: asdf-vm/actions/install@v3
        with:
          tool_versions: .tool-versions

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
Иногда разработчику нужно временно использовать другую версию инструмента для отладки, не меняя глобальный конфиг.

**Способы переопределения (по приоритету, от высшего к низшему):**

1. **Переменная окружения (самый высокий приоритет):**
```bash
# Переопределить версию Node для одной команды
NODE_VERSION=18.20.0 node -v  # → v18.20.0
```

2. **Локальный файл проекта (для asdf/mise):**
```bash
# .tool-versions.local (должен быть в .gitignore)
nodejs 18.20.0
python 3.11.9

# Файл автоматически подхватывается asdf/mise
```

3. **Временный override для asdf:**
```bash
# Установить версию только для текущей директории
asdf local nodejs 18.20.0

# Проверить
asdf current nodejs
# → nodejs 18.20.0 (set by /path/to/project/.tool-versions)
```

4. **Временный override для mise:**
```bash
# Установить версию только для текущей директории
mise use node@18.20.0

# Проверить
mise current nodejs
# → nodejs 18.20.0 (set by .mise.toml)
```

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
# → ~/.pyenv/shims/terraform             (pyenv)
# → /usr/local/bin/terraform             (не используется менеджер)

# Проверить конфигурационный файл
ls -la .tool-versions .mise.toml .python-version .nvmrc

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
- Использовать pinned версии в CI-шагах (`actions/checkout@v4` вместо `@v4` — конкретный хэш).
- Добавить шаг верификации версий в пайплайн.

---

## Рекомендации и ограничения

### Белые пятна и рекомендации

- **Git и .gitignore:** Файлы версий **ОБЯЗАТЕЛЬНО** должны быть в репозитории. Исключение — локальные переопределения (например, `.tool-versions.local`, `.mise.local.toml`, `.python-version.local`), которые стоит добавить в `.gitignore`.
- **.gitignore паттерны:**
```gitignore
# Версионные файлы — коммитим
.tool-versions
.mise.toml
.mise.toml.local.example
.envrc
rust-toolchain.toml

# Локальные переопределения — игнорируем
.tool-versions.local
.mise.local.toml
.envrc.local
.python-version.local
.terraform-version.local
```
- **Nix (flake.nix):** Современный подход к абсолютно воспроизводимым средам. Может сосуществовать с `mise` через интеграцию в `.envrc`. При использовании Nix файлы версий могут дублировать конфигурацию — выбирайте один источник истины.
- **Devcontainers:** Файл `devcontainer.json` часто дополняет файлы версий, описывая не только рантайм, но и расширения IDE и системные зависимости. DevContainer может использовать файлы версий через `postCreateCommand`.
- **Corepack (Node.js):** Современная альтернатива `nvm` для управления версиями `npm`, `yarn`, `pnpm`. Использует `package.json` поле `"packageManager"` и не требует отдельного файла версий.
- **Poetry / PDM (Python):** Менеджеры зависимостей, которые также управляют версиями интерпретатора через `pyproject.toml` поле `requires-python`. Могут заменять `.python-version` в проектах, где требуется строгая воспроизводимость через lock-файлы.

### Известные ограничения

- **Медленная компиляция pyenv:** Компиляция Python из исходников может занимать 5–15 минут. Используйте `pyenv install --list` для проверки доступных версий и `uv` для быстрого скачивания бинарников.
- **Плагины asdf:** Не все плагины поддерживают все ОС (macOS, Linux, WSL). Перед добавлением инструмента проверьте совместимость плагина.
- **Windows:** Многие менеджеры версий (asdf, pyenv, mise) имеют ограниченную поддержку Windows. Для Windows используйте `nvm-windows`, `scoop` или WSL2.
- **Версии в lock-файлах:** Файлы версий управляют версиями инструментов, но не гарантируют идентичность зависимостей. Для этого требуются lock-файлы (`package-lock.json`, `poetry.lock`, `Cargo.lock`, `go.sum`).

### Процедура миграции между менеджерами

При переходе с одного менеджера на другой:

```bash
# 1. Экспорт текущих версий
asdf list > current-versions.txt
mise current > current-versions.txt

# 2. Удаление старого менеджера
brew uninstall asdf  # или удаление вручную

# 3. Установка нового менеджера
curl https://mise.jdx.dev/install.sh | sh

# 4. Перенос конфигурации
# Для .tool-versions → .mise.toml автоматически поддерживается
cp .tool-versions .mise.toml

# 5. Верификация
mise install
mise current
```

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
- [rustup specification](https://rust-lang.github.io/rustup/overrides.html#the-toolchain-file)
- [direnv manual](https://direnv.net/)
- [nvm GitHub](https://github.com/nvm-sh/nvm)
- [pyenv GitHub](https://github.com/pyenv/pyenv)
