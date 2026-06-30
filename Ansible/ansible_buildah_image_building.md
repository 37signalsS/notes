# Сборка образов: Buildah и Ansible-bender

## Определения

- **Buildah** — инструмент для создания **OCI (Open Container Initiative)**-совместимых образов контейнеров без использования демона Docker. Позволяет собирать образы через shell-скрипты или `Dockerfile`.
- **Ansible-bender** — утилита-мост между Ansible и Buildah. Позволяет описывать сборку образа с помощью [плейбуков Ansible](PlaybookStructure/basics.md).

> **Статус проекта:** ansible-bender не имеет активного мейнтейнера с 2023 года (последний релиз 0.10.1). Для промышленной эксплуатации (production) рекомендуется оценить альтернативы или быть готовым к самостоятельной поддержке.

## Основные концепции

Buildah является низкоуровневым инструментом, и написание сложных скриптов на bash может быть громоздким. `ansible-bender` позволяет использовать роли, модули, переменные и шаблоны Ansible для описания процесса сборки.

**Ключевые преимущества:**

- **Унификация** — весь цикл (конфигурация серверов и сборка образов) описывается на языке Ansible.
- **Переиспользование кода** — существующие роли и задачи могут быть применены для сборки контейнеров.
- **Декларативность** — процесс сборки описывается в декларативном стиле, свойственном Ansible.

**Пример скрипта на Buildah:**

```bash
#!/usr/bin/env bash
set -x
ctrl=$(buildah from fedora)
buildah run "$ctrl" -- dnf update -y && dnf install -y lighttpd
buildah config --cmd "/usr/sbin/lighttpd -D -f /etc/lighttpd/lighttpd.conf" "$ctrl"
buildah config --port 80 "$ctrl"
buildah commit "$ctrl" my-lighttpd-image
# → Образ my-lighttpd-image успешно сохранен в локальном хранилище
```

## Практические сценарии

### 1. Установка компонентов

Для работы требуются Python версии выше 3.6, а также утилиты `buildah` и `podman`.

```bash
# Установка ansible-bender
sudo pip3 install ansible-bender
# → Successfully installed ansible-bender...

# Установка buildah и podman (для RHEL/CentOS)
sudo yum -y install buildah podman
# → Complete!
```

### 2. Пример плейбука для сборки образа

Плейбук для `ansible-bender` выглядит как стандартный сценарий, но параметры сборки объявляются в специальном словаре `ansible_bender`.

```yaml
---
- name: Сборка образа через ansible-bender
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
    - name: Проверить содержимое рабочей директории
      ansible.builtin.command: ls -lha /src

    - name: Проверить наличие конфигурационного файла
      ansible.builtin.stat:
        path: "{{ lookup('env', 'FILE_TO_PROCESS') }}"
```

### 3. Сборка напрямую через Ansible (без bender)

Если `ansible-bender` избыточен или не подходит, можно управлять Buildah напрямую через стандартные модули `command` или `shell`, регистрируя результаты для передачи ID контейнера между задачами.

```yaml
- name: Сборка образа через прямые вызовы Buildah
  hosts: localhost
  tasks:
    - name: Предварительно скачать базовый образ
      ansible.builtin.command: buildah pull alpine
      register: pull_out

    - name: Создать рабочий контейнер
      ansible.builtin.command: buildah from alpine
      register: from_out

    - name: Установить пакет внутри контейнера
      ansible.builtin.command: 
        cmd: buildah run {{ from_out.stdout }} -- apk add nginx

    - name: Настроить точку входа
      ansible.builtin.command:
        cmd: buildah config --entrypoint '["nginx", "-g", "daemon off;"]' {{ from_out.stdout }}

    - name: Зафиксировать образ
      ansible.builtin.command:
        cmd: buildah commit {{ from_out.stdout }} my-custom-nginx
      register: commit_out

    - name: Удалить рабочий контейнер
      ansible.builtin.command:
        cmd: buildah rm {{ from_out.stdout }}

    - name: Показать результат
      ansible.builtin.debug:
        msg: "Образ собран с ID: {{ commit_out.stdout }}"
```

### 4. Управление процессом сборки (bender)

## Дополнительная информация

Переход на `ansible-bender` целесообразен, если ваша инфраструктура уже плотно завязана на Ansible и вы хотите унифицировать процесс доставки. В CentOS 7 убедитесь, что Ansible установлен через `pip3`, так как системные пакеты могут использовать Python 2, который не поддерживается инструментом.

- [Buildah: Концепции и практика](../Podman/buildah_overview.md) — подробное руководство по инструменту.
- [Тестирование ролей с Molecule](ansible_testing_with_molecule.md) — автоматизация проверок перед сборкой.
- [Оптимизация производительности Ansible](ansible_performance_tuning.md) — ускорение выполнения плейбуков.
