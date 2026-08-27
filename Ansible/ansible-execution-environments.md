# Среды выполнения Ansible (Execution Environments)

## Определения

**Execution Environment (EE)** — это стандартизированный OCI-совместимый контейнерный образ, который служит в качестве узла управления (Control Node) для запуска автоматизации Ansible. EE объединяет в себе:
*   **Ansible Core** (движок выполнения).
*   **Ansible Collections** (модули и плагины).
*   **Python-зависимости** (библиотеки, необходимые для работы модулей).
*   **Системные зависимости** (бинарные файлы и библиотеки ОС, такие как `sshpass`, `git`, `rsync`, `python3-devel`).

**ansible-builder** — специализированная утилита для автоматизированной сборки образов EE на основе декларативного YAML-файла конфигурации. Она автоматизирует создание многоэтапных (multi-stage) Docker/Container-файлов.

**ansible-navigator** — современный CLI/TUI инструмент для запуска плейбуков, инспекции образов и просмотра документации, который обеспечивает идентичность сред выполнения между разработкой и эксплуатацией.

**execution-environment.yml** — декларативный YAML-файл, описывающий зависимости и параметры сборки EE.

**Container Engine** — OCI-совместимый движок контейнеров (Podman, Docker), используемый для запуска EE.

---

## Основные концепции

До появления EE (версии до Ansible 2.11) зависимости устанавливались напрямую на хост Control Node. Это приводило к проблемам «dependency hell», когда разные проекты требовали конфликтующих версий коллекций или Python-библиотек. EE решает эту проблему, инкапсулируя всё необходимое в переносимый контейнер.

### Преимущества использования EE
*   **Изоляция:** Каждая автоматизация работает в своей чистой, предсказуемой среде.
*   **Воспроизводимость:** Гарантия того, что плейбук, протестированный локально, отработает идентично в CI/CD или в продакшене.
*   **Масштабируемость:** Узлы выполнения (Execution Nodes) в Ansible Automation Platform (AAP) или AWX могут динамически запускать контейнеры EE на различных хостах без их предварительной настройки.
*   **Упрощение пайплайнов:** В CI больше не требуется устанавливать зависимости через `pip install` или `ansible-galaxy` при каждом запуске.

### Сравнение: EE vs Virtualenv

| Критерий | Execution Environment | Virtualenv |
| :--- | :--- | :--- |
| **Изоляция** | Полная (процессная + файловая) | Частичная (только Python) |
| **Воспроизводимость** | 100% (образ неизменяемый) | Зависит от хоста |
| **Переносимость** | Высокая (OCI-образ) | Низкая (привязка к хосту) |
| **Накладные расходы** | Средние (старт контейнера) | Минимальные |
| **Сложность настройки** | Средняя | Низкая |
| **Безопасность** | Высокая (rootless, namespaces) | Средняя |
| **Использование в CI/CD** | Рекомендуется | Допустимо |

### Архитектура EE

```
┌─────────────────────────────────────────┐
│         Execution Environment           │
├─────────────────────────────────────────┤
│  ┌─────────────────────────────────┐    │
│  │      Ansible Core (2.17+)       │    │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │      Ansible Collections        │    │
│  │  (kubernetes.core, aws, etc.)   │    │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │      Python Libraries           │    │
│  │  (boto3, kubernetes, etc.)      │    │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │      System Packages            │    │
│  │  (git, sshpass, openssh)        │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

---

## Практические сценарии

### Создание кастомного Execution Environment

Процесс сборки EE состоит из описания зависимостей в YAML и запуска `ansible-builder`.

#### Шаг 1: Описание конфигурации `execution-environment.yml`

Рекомендуется использовать `version: 3` (поддерживается в `ansible-builder` 3.0+), так как она предоставляет наиболее гибкие механизмы настройки.

```yaml
version: 3

images:
  base_image:
    name: quay.io/ansible/ansible-runner:latest

dependencies:
  ansible_core:
    package_pip: ansible-core>=2.17.0
  ansible_runner:
    package_pip: ansible-runner
  
  galaxy:
    collections:
      - name: kubernetes.core
      - name: community.general
      - name: amazon.aws
        version: ">=8.0.0"

  python:
    - kubernetes
    - boto3
    - botocore

  system:
    - git
    - openssh-clients
    - iputils

additional_build_steps:
  prepend_base:
    - RUN echo "Настройка базового слоя"
  append_final:
    - RUN alternatives --set python /usr/bin/python3
    - COPY ./scripts/custom-init.sh /usr/local/bin/
```

#### Шаг 2: Управление сложными зависимостями

Если проект требует специфических системных библиотек или Python-пакетов, их можно вынести в отдельные файлы для удобства поддержки.

1.  **Системные пакеты (`bindep.txt`):**
    Используется формат `bindep`. Позволяет указывать пакеты в зависимости от дистрибутива (RHEL, Debian).
    ```text
    libxml2-devel [platform:rpm]
    libxml2-dev [platform:dpkg]
    make
    gcc
    ```

2.  **Python пакеты (`requirements.txt`):**
    Стандартный формат pip.
    ```text
    requests>=2.31.0
    pyyaml
    ```

3.  **Коллекции Ansible (`requirements.yml`):**
    ```yaml
    collections:
      - name: google.cloud
        version: 1.0.0
    ```

**Подключение внешних файлов в `execution-environment.yml`:**
```yaml
dependencies:
  python: requirements.txt
  system: bindep.txt
  galaxy: requirements.yml
```

#### Шаг 3: Сборка образа

Для сборки требуется установленный `podman` (рекомендуется) или `docker`.

```bash
# Сборка образа с тегом
ansible-builder build --tag my-custom-ee:v1.0.0

# Проверка наличия образа
podman images | grep my-custom-ee
```

`ansible-builder` генерирует промежуточный `context`, содержащий `Containerfile`. Вы можете изучить его в директории `context/`, чтобы понять, как строятся слои.

### Запуск и настройка проекта через ansible-navigator

Вместо длинных командных строк используйте файл конфигурации `ansible-navigator.yml` в корне проекта.

**Пример `ansible-navigator.yml`:**
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

**Запуск:**
```bash
ansible-navigator run site.yml --mode stdout
```

### Переменные окружения в EE

Ansible передает определенные переменные окружения в контейнер EE:

```yaml
# В ansible-navigator.yml
ansible-navigator:
  execution-environment:
    environment-variables:
     ARA_API_SERVER: "http://ara.example.com"
      ANSIBLE_FORCE_COLOR: "true"
      ANSIBLE_NOCOWS: "1"
    container-options:
      - "--pull=missing"
      - "--quiet"
```

### Кастомный entrypoint

Для выполнения предварительных действий перед запуском Ansible:

```bash
#!/bin/bash
# custom-entrypoint.sh
echo "Initializing Execution Environment..."
echo "Python: $(python3 --version)"
echo "Ansible: $(ansible --version | head -1)"

# Выполнение команды
exec "$@"
```

```yaml
# В execution-environment.yml
additional_build_steps:
  append_final:
    - COPY custom-entrypoint.sh /opt/custom-entrypoint.sh
    - RUN chmod +x /opt/custom-entrypoint.sh

# В ansible-navigator.yml
ansible-navigator:
  execution-environment:
    container-options:
      - "--entrypoint=/opt/custom-entrypoint.sh"
```

---

## Безопасность и оптимизация

### Безопасность образов (Supply Chain Security)
1.  **Подпись образов:** Используйте `cosign` или встроенные механизмы реестров для подписи EE-образов. Это критично при использовании в AWX/AAP.
2.  **Rootless Podman:** Всегда запускайте сборку и выполнение EE в rootless-режиме для минимизации рисков компрометации хоста.
3.  **Минимальные образы:** В качестве `base_image` для продакшена используйте `minimal` образы (например, на базе RHEL UBI), отключая ненужные утилиты.
4.  **Сканирование уязвимостей:** Используйте `trivy` или `grype` для проверки образов перед деплоем:
    ```bash
    trivy image my-custom-ee:v1.0.0
    grype my-custom-ee:v1.0.0
    ```
5.  **Пиннинг версий:** Всегда указывайте конкретные версии зависимостей в `execution-environment.yml` для воспроизводимости.

### Интеграция с AWX / Ansible Automation Platform (AAP)
Подробное описание платформы и её компонентов доступно в разделе **[Ansible Automation Platform (AAP)](./ansible-automation-platform.md)**.

Для использования кастомного EE в платформе:
1.  Запушьте образ в доверенный реестр (Harbor, Quay).
2.  В интерфейсе AWX/AAP перейдите в **Execution Environments** и добавьте новый EE, указав путь к образу и параметры Pull Policy.
3.  Назначьте EE конкретному **Job Template** или проекту.

### Оптимизация слоев
1.  **Порядок зависимостей:** Размещайте редко меняющиеся зависимости (системные пакеты) выше часто меняющихся (внутренние коллекции).
2.  **Многоэтапная сборка:** `ansible-builder` по умолчанию использует multi-stage билд, удаляя инструменты сборки (gcc, devel-пакеты) из финального слоя, что существенно уменьшает размер образа.
3.  **Кеширование:** Используйте `--no-cache` для полной пересборки или `--cache` для использования кеша предыдущих сборок.

### Мультиархитектурные сборки

Для поддержки разных архитектур (amd64, arm64):

```bash
# Установка поддержки мультиархитектуры
podman manifest create my-custom-ee:latest

# Сборка для разных архитектур
ansible-builder build --tag my-custom-ee:latest-amd64 --build-arg ARCH=amd64
ansible-builder build --tag my-custom-ee:latest-arm64 --build-arg ARCH=arm64

# Объединение в манифест
podman manifest add my-custom-ee:latest my-custom-ee:latest-amd64
podman manifest add my-custom-ee:latest my-custom-ee:latest-arm64
podman manifest push my-custom-ee:latest
```

---

## Отладка и устранение проблем

### Инспекция содержимого образа
Чтобы увидеть установленные коллекции, роли и версии библиотек:
```bash
ansible-navigator images
# В TUI выберите образ и нажмите 'i' для инспекции (Inspect) или 'c' для списка коллекций.
```

### Интерактивная отладка внутри EE
Если плейбук падает из-за отсутствия зависимости или ошибки окружения, можно зайти внутрь контейнера:
```bash
podman run --rm -it my-custom-ee:v1.0.0 bash
# Внутри проверьте:
ansible --version
pip list | grep <package>
ansible-galaxy collection list
```

### Диагностические команды

```bash
# Просмотр информации об образе
podman inspect my-custom-ee:v1.0.0

# Проверка размера образа
podman images my-custom-ee:v1.0.0

# Просмотр слоев образа
podman history my-custom-ee:v1.0.0

# Запуск с отладкой
ansible-navigator run site.yml -m stdout --vvv

# Проверка конфигурации ansible-navigator
ansible-navigator config dump

# Просмотр логов сборки
ansible-builder build --tag my-custom-ee:v1.0.0 --log-level debug
```

### Таблица типовых ошибок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Error: unable to find image` | Образ не найден локально | Проверьте `podman images` или добавьте `--pull=always` |
| `Permission denied` | Rootless-режим или права доступа | Используйте `podman unshare` или проверьте права |
| `ModuleNotFoundError` | Python-зависимость отсутствует | Добавьте пакет в `requirements.txt` |
| `Collection not found` | Коллекция не установлена | Добавьте в `requirements.yml` |
| `Containerfile parse error` | Ошибка в `execution-environment.yml` | Проверьте YAML-синтаксис и версию формата |
| `dial tcp: lookup ghcr.io` | Проблемы с DNS | Проверьте сеть или используйте прокси |
| `error building image` | Ошибка в `additional_build_steps` | Проверьте Dockerfile-синтаксис в `context/` |
| `ansible-playbook: command not found` | Ansible не установлен в EE | Проверьте `ansible_core.package_pip` |
| `timeout expired` | Медленная загрузка зависимостей | Увеличьте таймаут или используйте кеш |
| `certificate signed by unknown authority` | Проблемы с сертификатами | Добавьте CA-сертификат в `additional_build_steps` |

---

## Дополнительная информация

### Смотрите также
*   **[Сборка образов через Buildah](./ansible_buildah_image_building.md)** — если требуется максимальный контроль над процессом сборки без YAML-обертки.
*   **[Установка и настройка Ansible-navigator](./ansible_setup_and_config.md#инструменты-современной-экосистемы)** — подробнее о CLI/TUI интерфейсе.
*   **[Лучшие практики CI/CD](../CI-CD/ci_cd_patterns.md)** — общие подходы к интеграции автоматизации в пайплайны.
*   **[Интеграция Ansible с GitLab CI/CD](../CI-CD/GitLab_CI/Tutorials/ansible_integration.md)** — практическое применение EE в GitLab.
