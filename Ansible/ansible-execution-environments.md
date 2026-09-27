# Среды выполнения Ansible (Execution Environments)

## Определения

**Execution Environment (EE)** — стандартизированный OCI-совместимый контейнерный образ, служащий изолированным узлом управления (Control Node) для запуска автоматизации Ansible. EE инкапсулирует все зависимости проекта: Ansible Core, коллекции, Python-библиотеки и системные пакеты, исключая проблему «dependency hell» на Shared Control Node.

**ansible-builder** — специализированная утилита для декларативной сборки образов EE на основе YAML-файла конфигурации. Генерирует многоэтапный `Containerfile` (для Podman) или `Dockerfile` (для Docker) и управляет контекстом сборки в директории `context/`.

**ansible-navigator** — современный CLI/TUI-инструмент для запуска плейбуков внутри EE, инспекции образов и просмотра документации. Обеспечивает идентичность сред выполнения между разработкой, CI/CD и эксплуатацией.

**execution-environment.yml** — декларативный YAML-файл, описывающий зависимости и параметры сборки EE. Рекомендуемая версия схемы — `3` (требует `ansible-builder` 3.0+).

**Container Engine** — OCI-совместимый движок контейнеров (Podman, Docker), используемый для сборки и запуска EE. Рекомендуется Podman в rootless-режиме для повышения безопасности.

**bindep.txt** — файл со списком системных зависимостей в формате `bindep`, позволяющий указывать пакеты с привязкой к дистрибутиву (`[platform:rpm]`, `[platform:dpkg]`).

**context/** — директория, генерируемая `ansible-builder`, содержащая `Containerfile`, внешние файлы зависимостей и артефакты сборки. Позволяет inspectить и вручную модифицировать процесс сборки.

---

## Основные концепции

### Проблема, которую решает EE

До Ansible 2.11 все зависимости устанавливались напрямую на хост Control Node. При работе над несколькими проектами возникали конфликты версий коллекций и Python-библиотек. EE решает эту проблему, упаковывая всё необходимое в переносимый неизменяемый контейнерный образ.

### Архитектура Execution Environment

```
┌──────────────────────────────────────────────┐
│           Execution Environment              │
├──────────────────────────────────────────────┤
│  ┌────────────────────────────────────────┐  │
│  │         Ansible Core (2.21+)           │  │
│  │     (движок, парсер, исполнитель)      │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │       Ansible Collections              │  │
│  │  (community.general, ansible.posix,    │  │
│  │   community.network, community.crypto) │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │      Python Libraries                  │  │
│  │  (requests, pyyaml, jinja2, psycopg2)  │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │      System Packages                   │  │
│  │  (git, openssh-clients, sshpass,       │  │
│  │   iputils, libxml2-devel)              │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │      Ansible Runner                    │  │
│  │  (обертка для запуска плейбуков        │  │
│  │   в контейнеризированном окружении)    │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

### Жизненный цикл сборки EE

1. **Определение:** Описание зависимостей в `execution-environment.yml` (версия 3).
2. **Генерация контекста:** `ansible-builder create` создает директорию `context/` с `Containerfile` и копирует внешние файлы зависимостей.
3. **Сборка образа:** `ansible-builder build` выполняет многоэтапную сборку:
   - **Этап 1 (base):** Загрузка базового образа.
   - **Этап 2 (builder):** Установка системных и Python-зависимостей, коллекций Galaxy.
   - **Этап 3 (final):** Очистка инструментов сборки (gcc, devel-пакеты), финальный слой с готовым окружением.
4. **Публикация:** Загрузка образа в реестр (Harbor, Quay, Docker Hub) или использование локально.

### Сравнение: EE vs Virtualenv vs Домашний Control Node

| Критерий | Execution Environment | Virtualenv | Control Node (host) |
| :--- | :--- | :--- | :--- |
| **Изоляция** | Полная (процесс + файловая система + сеть) | Частичная (только Python) | Отсутствует |
| **Воспроизводимость** | 100% (образ неизменяем) | Зависит от хоста | Зависит от хоста |
| **Переносимость** | Высокая (OCI-образ) | Низкая (привязка к хосту) | Отсутствует |
| **Накладные расходы** | Средние (старт контейнера ~1-2с) | Минимальные | Минимальные |
| **Сложность настройки** | Средняя | Низкая | Низкая |
| **Безопасность** | Высокая (rootless, namespaces) | Средняя | Зависит от хоста |
| **Использование в CI/CD** | Рекомендуется | Допустимо для простых случаев | Не рекомендуется |
| **Поддержка AAP/AWX** | Нативная | Отсутствует | Ограниченная |

---

## Практические сценарии

### Предварительные требования

- **ansible-builder** 3.0+ (`pip install ansible-builder`)
- **Container Engine:** Podman (рекомендуется) или Docker
- **Python:** 3.12–3.14 на хосте сборки (совместимо с ansible-core 2.21)
- **Доступ к реестру:** При публикации образов — учетные данные для pushes
- **Git:** Для зависимостей, указываемых по Git URL

### Создание кастомного Execution Environment

#### Шаг 1: Базовая конфигурация `execution-environment.yml`

Используйте `version: 3` для доступа ко всем возможностям `ansible-builder` 3.x.

```yaml
version: 3

images:
  base_image:
    name: docker.io/redhat/ubi9:latest

dependencies:
  ansible_core:
    package_pip: ansible-core>=2.21
  ansible_runner:
    package_pip: ansible-runner

  galaxy:
    collections:
      - name: community.general
      - name: ansible.posix
      - name: community.network
        version: ">=5.0.0"

  python:
    - requests>=2.31.0
    - pyyaml
    - jinja2

  system:
    - git
    - openssh-clients
    - sshpass
    - iputils
    - libxml2-devel [platform:rpm]
    - libxml2-dev [platform:dpkg]

additional_build_steps:
  prepend_base:
    - RUN echo "Настройка базового слоя"
  append_final:
    - RUN alternatives --set python /usr/bin/python3
    - COPY ./scripts/custom-init.sh /usr/local/bin/
```

> **Примечание:** Для cloud-специфичных коллекций (`amazon.aws`, `google.cloud`, `kubernetes.core`) и их SDK (`boto3`, `botocore`, `kubernetes`) создавайте отдельные профили EE во избежание увеличения размера образа и расширения поверхности атаки.

#### Шаг 2: Управление сложными зависимостями внешними файлами

Для крупных проектов выносите зависимости в отдельные файлы:

**`bindep.txt` — системные пакеты:**
```text
git
openssh-clients
sshpass
iputils
libxml2-devel [platform:rpm]
libxml2-dev [platform:dpkg]
gcc [platform:rpm]
build-essential [platform:dpkg]
```

**`requirements.txt` — Python-зависимости:**
```text
requests>=2.31.0
pyyaml>=6.0
jinja2>=3.1
psycopg2-binary
```

**`requirements.yml` — коллекции Galaxy:**
```yaml
collections:
  - name: community.general
  - name: ansible.posix
  - name: community.network
    version: ">=5.0.0"
```

**Подключение внешних файлов в `execution-environment.yml`:**
```yaml
dependencies:
  python: requirements.txt
  system: bindep.txt
  galaxy: requirements.yml
```

**.containerignore — исключения из контекста сборки:**
```text
.git
.vscode
__pycache__
*.pyc
context/
node_modules
```

#### Шаг 3: Генерация контекста сборки

```bash
# Генерация Containerfile/Dockerfile без сборки образа
ansible-builder create --output-dir ./context

# Просмотр сгенерированного Containerfile
cat ./context/Containerfile
```

#### Шаг 4: Сборка и проверка образа

```bash
# Сборка образа
ansible-builder build --tag my-custom-ee:v1.0.0

# Проверка размера образа
podman images my-custom-ee:v1.0.0

# Инспекция слоев
podman history my-custom-ee:v1.0.0
```

#### Шаг 5: Запуск через ansible-navigator

**Файл `ansible-navigator.yml`:**
```yaml
ansible-navigator:
  execution-environment:
    image: my-custom-ee:v1.0.0
    enabled: true
    container-engine: podman
    pull:
      policy: missing
  ansible:
    config: ./ansible.cfg
    inventory: ./inventory/hosts.yml
  playbook-artifact:
    enable: true
    save-as: ./artifacts/playbook-out.json
```

**Запуск плейбука:**
```bash
ansible-navigator run site.yml --mode stdout
# → Запуск внутри изолированного контейнера EE
```

### Переменные окружения в EE

```yaml
# В ansible-navigator.yml
ansible-navigator:
  execution-environment:
    environment-variables:
      ANSIBLE_FORCE_COLOR: "true"
      ANSIBLE_NOCOWS: "1"
      ANSIBLE_RETRY_FILES_ENABLED: "false"
    container-options:
      - "--pull=missing"
      - "--quiet"
      - "--volume=/mnt/data:/data:Z"
```

### Кастомный entrypoint

```bash
#!/bin/bash
# scripts/custom-init.sh
echo "Initializing Execution Environment..."
echo "Python: $(python3 --version)"
echo "Ansible: $(ansible --version | head -1)"

# Проверка подключения к внешним сервисам
# curl -sf http://internal-service:8080/health || echo "Warning: service unavailable"

exec "$@"
```

```yaml
# В execution-environment.yml
additional_build_steps:
  append_final:
    - COPY scripts/custom-init.sh /usr/local/bin/
    - RUN chmod +x /usr/local/bin/custom-init.sh

# В ansible-navigator.yml
ansible-navigator:
  execution-environment:
    container-options:
      - "--entrypoint=/usr/local/bin/custom-init.sh"
```

---

## Операции и команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `ansible-builder build` | Сборка образа EE | `ansible-builder build --tag my-ee:v1.0.0` |
| `ansible-builder create` | Генерация `Containerfile` без сборки | `ansible-builder create --output-dir ./context` |
| `ansible-builder --version` | Проверка версии ansible-builder | `ansible-builder --version # → ansible-builder 3.x` |
| `podman images` | Просмотр локальных образов | `podman images \| grep my-ee` |
| `podman inspect` | Детальная информация об образе | `podman inspect my-ee:v1.0.0` |
| `podman history` | Просмотр слоев образа | `podman history my-ee:v1.0.0` |
| `podman run --rm -it` | Интерактивный запуск для отладки | `podman run --rm -it my-ee:v1.0.0 bash` |
| `ansible-navigator images` | Список образов в TUI | `ansible-navigator images` |
| `ansible-navigator run` | Запуск плейбука в EE | `ansible-navigator run site.yml --mode stdout` |
| `ansible-navigator config dump` | Проверка конфигурации | `ansible-navigator config dump` |
| `ansible-galaxy collection list` | Просмотр установленных коллекций | `ansible-galaxy collection list` |
| `pip list` | Просмотр Python-пакетов | `pip list \| grep requests` |
| `trivy image` | Сканирование уязвимостей | `trivy image my-ee:v1.0.0` |
| `grype` | Сканирование уязвимостей (альтернатива) | `grype my-ee:v1.0.0` |

---

## Диагностика и устранение неполадок

### Типовые ошибки сборки

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Error: unable to find image` | Образ не найден локально | Проверьте `podman images` или добавьте `--pull=always` |
| `Permission denied` | Rootless-режим или права доступа | Используйте `podman unshare` или проверьте SELinux контекст |
| `ModuleNotFoundError` | Python-зависимость отсутствует | Добавьте пакет в `requirements.txt` или секцию `dependencies.python` |
| `Collection not found` | Коллекция не установлена | Добавьте в `dependencies.galaxy.collections` или `requirements.yml` |
| `Containerfile parse error` | Ошибка в `execution-environment.yml` | Проверьте YAML-синтаксис и версию схемы (`version: 3`) |
| `dial tcp: lookup ...` | Проблемы с DNS | Проверьте `/etc/resolv.conf` или используйте прокси |
| `error building image` | Ошибка в `additional_build_steps` | Проверьте синтаксис в сгенерированном `context/Containerfile` |
| `ansible-playbook: command not found` | Ansible не установлен в EE | Проверьте `ansible_core.package_pip` в конфигурации |
| `timeout expired` | Медленная загрузка зависимостей | Увеличьте таймаут или используйте кеш (`--cache`) |
| `certificate signed by unknown authority` | Проблемы с сертификатами | Добавьте CA-сертификат в `additional_build_steps` |
| `GPG error` | Проблема с подписью репозитория | Импортируйте GPG-ключ в `prepend_base` |
| `No space left on device` | Недостаточно места на диске | Очистите кеш (`podman system prune -a`) или увеличение раздела |
| `bindep: command not found` | Bindep не установлен на хосте | `pip install bindep` |
| `Killed` | OOM Killer завершил процесс | Увеличьте `memory` в конфигурации Podman/Docker |

### Инспекция содержимого образа

```bash
# Список установленных коллекций и версий
podman run --rm my-custom-ee:v1.0.0 ansible-galaxy collection list

# Проверка Python-пакетов
podman run --rm my-custom-ee:v1.0.0 pip list

# Проверка версии Ansible
podman run --rm my-custom-ee:v1.0.0 ansible --version
# → ansible [core 2.21.x]
```

### Интерактивная отладка внутри EE

```bash
# Запуск оболочки внутри контейнера
podman run --rm -it my-custom-ee:v1.0.0 bash

# Проверка окружения
ansible --version
python3 --version
ansible-galaxy collection list
pip list | grep <package>
```

---

## Рекомендации и лучшие практики

### Безопасность образов (Supply Chain Security)

1. **Пиннинг версий:** Всегда указывайте конкретные версии зависимостей в `execution-environment.yml`. Избегайте `:latest` для базовых образов в продакшене.
2. **Подпись образов:** Используйте `cosign` или встроенные механизмы реестров для подписи EE-образов. Это критично при использовании в AWX/AAP.
3. **Rootless Podman:** Всегда запускайте сборку и выполнение EE в rootless-режиме для минимизации рисков компрометации хоста.
4. **Минимальные образы:** В качестве `base_image` для продакшена используйте минимальные образы (например, `docker.io/redhat/ubi9-minimal`), отключая ненужные утилиты.
5. **Сканирование уязвимостей:** Используйте `trivy` или `grype` для проверки образов перед деплоем:
   ```bash
   trivy image my-custom-ee:v1.0.0
   grype my-custom-ee:v1.0.0
   ```
6. **Доверенные реестры:** Храните образы в изолированных реестрах (Harbor, Quay) с включенным сканированием и политиками подписи.

### Оптимизация размера и скорости сборки

1. **Порядок слоев:** Размещайте редко меняющиеся зависимости (системные пакеты) выше часто меняющихся (внутренние коллекции, код).
2. **Многоэтапная сборка:** `ansible-builder` по умолчанию использует multi-stage билд, удаляя инструменты сборки (gcc, devel-пакеты) из финального слоя.
3. **Кеширование:** Используйте `--no-cache` для полной пересборки или `--cache` для ускорения повторных сборок.
4. **Исключения:** Используйте `.containerignore` для исключения лишних файлов из контекста сборки.
5. **Минимальные зависимости:** Включайте только те коллекции и пакеты, которые фактически используются плейбуками. Каждая лишняя зависимость увеличивает размер образа и время сборки.

### Интеграция с AWX / Ansible Automation Platform (AAP)

Подробное описание платформы доступно в разделе **[Ansible Automation Platform (AAP)](./ansible-automation-platform.md)**.

Для использования кастомного EE:
1. Запушьте образ в доверенный реестр (Harbor, Quay).
2. В интерфейсе AWX/AAP перейдите в **Execution Environments** и добавьте новый EE.
3. Назначьте EE конкретному **Job Template**, **Workflow Job Template** или **Project**.

> **Важно:** В AAP 2.7+ удалено соглашение `:latest` для минимального EE — требуется явное указание версии образа.

### Мультиархитектурные сборки

```bash
# Создание манифеста для мультиархитектуры
podman manifest create my-custom-ee:v1.0.0

# Сборка для amd64
ansible-builder build --tag my-custom-ee:v1.0.0-amd64 --build-arg ARCH=amd64

# Сборка для arm64
ansible-builder build --tag my-custom-ee:v1.0.0-arm64 --build-arg ARCH=arm64

# Объединение в манифест
podman manifest add my-custom-ee:v1.0.0 my-custom-ee:v1.0.0-amd64
podman manifest add my-custom-ee:v1.0.0 my-custom-ee:v1.0.0-arm64

# Публикация манифеста
podman manifest push my-custom-ee:v1.0.0
```

---

## Дополнительная информация

### Смотрите также

*   **[Сборка образов через Buildah](./ansible_buildah_image_building.md)** — альтернативный подход с полным контролем над `Containerfile` без YAML-обертки.
*   **[Установка и настройка Ansible-navigator](./ansible_setup_and_config.md#инструменты-современной-экосистемы)** — подробнее о CLI/TUI интерфейсе.
*   **[Анализ производительности Ansible](./ansible_performance_tuning.md)** — влияние EE на скорость выполнения плейбуков и стратегии кеширования зависимостей.
*   **[Лучшие практики безопасности](./ansible_security_best_practices.md)** — защита Control Node, управление секретами и аудит выполнения в EE.

### Примечания

- **Версия ansible-core:** Рекомендуется использовать `ansible-core>=2.21` (текущая стабильная на май 2026). Старые версии (2.14 и ниже) имеют EOL-статус и не поддерживаются.
- **Python на хосте сборки:** Для ansible-core 2.21 требуется Python 3.12–3.14.
- **Registry:** Любой OCI-совместимый реестр (Docker Hub, Quay, Harbor, GHCR) может использоваться для хранения EE-образов. Выбор реестра зависит от политик безопасности организации.
- **Совместимость:** EE, собранные с `ansible-builder` 3.x, не совместимы с `ansible-builder` 1.x/2.x из-за изменения схемы `execution-environment.yml`.
