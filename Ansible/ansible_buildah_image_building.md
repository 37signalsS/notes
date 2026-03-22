# Ansible Buildah Image Building

## Определения

**Buildah** — инструмент для создания OCI-совместимых образов контейнеров без Docker-демона. Позволяет собирать образы через shell-скрипты или `Dockerfile`.

**Ansible-bender** — утилита-мост между Ansible и Buildah. Позволяет описывать сборку образа с помощью [плейбуков Ansible](PlaybookStructure/basics.md).

> **Статус проекта:** ansible-bender не имеет активного мейнтейнера с 2023 года (последний релиз 0.10.1). Проект ищет сопровождающих. Для production рекомендуется оценить альтернативы или быть готовым к самостоятельной поддержке.

## Основные концепции

Buildah — низкоуровневый инструмент, написание сложных скриптов на bash громоздко. `ansible-bender` позволяет использовать роли, модули, переменные и шаблоны Ansible для описания сборки.

**Преимущества:**

- **Унификация** — весь пайплайн (конфигурация серверов и сборка образов) описывается в Ansible.
- **Переиспользование кода** — существующие роли и задачи используются для сборки образов.
- **Декларативность** — процесс сборки описывается в стиле Ansible.

**Пример скрипта на чистом Buildah:**

```bash
#!/usr/bin/env bash
set -x
ctrl=$(buildah from fedora)
buildah run "$ctrl" -- dnf update -y && dnf install -y lighttpd
buildah config --cmd "/usr/sbin/lighttpd -D -f /etc/lighttpd/lighttpd.conf" "$ctrl"
buildah config --port 80 "$ctrl"
buildah commit "$ctrl" my-lighttpd-image
```

## Практические сценарии

### 1. Установка

Требования: Python > 3.6, утилиты `buildah` и `podman`.

```bash
# Установка ansible-bender
sudo pip3 install ansible-bender

# Установка buildah и podman
sudo yum -y install buildah podman
```

### 2. Пример плейбука для сборки

Плейбук для `ansible-bender` выглядит как обычный, но переменные сборки объявляются в словаре `ansible_bender`.

```yaml
# playbook.yml
- name: Демонстрация функциональности ansible-bender
  hosts: localhost
  vars:
    ansible_bender:
      base_image: python:3-alpine
      target_image:
        name: my-nice-app
      working_container:
        volumes:
          - '{{ playbook_dir }}:/src'
      working_dir: /src
      labels:
        built-by: 'ansible-bender'
      environment:
        FILE_TO_PROCESS: README.md

  tasks:
    - name: Показать содержимое рабочей директории
      command: 'ls -lha /src'

    - name: Проверить наличие файла
      stat:
        path: "{{ lookup('env','FILE_TO_PROCESS') }}"
```

### 3. Процесс сборки и управление

```bash
# Запуск сборки
ansible-bender build playbook.yml

# Просмотр списка сборок
ansible-bender list-builds

# Получение логов сборки
ansible-bender get-logs <BUILD_ID>
```

## Дополнительная информация

**Когда использовать:** если инфраструктура уже на `Dockerfile`, переход может не иметь смысла. Подход полезен для унификации пайплайна на Ansible или при сложности сборки за рамками `Dockerfile`.

**Проблемы:** на CentOS 7 Ansible из стандартных репозиториев может использовать Python 2, с которым `ansible-bender` не работает. Установите Ansible через `pip3`.

См. также [тестирование с Molecule](ansible_testing_with_molecule.md), [оптимизация производительности](ansible_performance_tuning.md), [пользовательские модули](ansible_custom_modules.md).
