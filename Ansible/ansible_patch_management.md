# Ansible Patch Management: Стратегии и жизненный цикл обновления ОС

## Определения

- **Управление обновлениями (Patch Management)** — процесс систематического обновления программного обеспечения (чаще всего ядер ОС и системных пакетов) для исправления уязвимостей (CVE), повышения производительности и обеспечения стабильности инфраструктуры.
- **CVE (Common Vulnerabilities and Exposures)** — база данных общеизвестных уязвимостей информационной безопасности. Управление патчами напрямую связано с устранением CVE.
- **Окно обслуживания (Maintenance Window)** — запланированный период времени, в течение которого допускается временная недоступность сервисов для проведения регламентных работ.
- **Rolling Update (Последовательное обновление)** — стратегия, при которой узлы кластера обновляются по очереди или небольшими группами, что позволяет минимизировать простой приложения.
- **Canary Update (Канареечное обновление)** — метод, при котором обновление сначала применяется к одному или нескольким «тестовым» узлам для проверки стабильности перед массовой раскаткой.
- **Pre-Patching / Post-Patching** — этапы подготовки (проверка здоровья, создание снимков) и верификации (проверка работы служб) до и после непосредственной установки пакетов.

## Жизненный цикл управления патчами

Современный подход к патчингу в Ansible строится на трехфазной модели, обеспечивающей максимальную безопасность и аудит.

### Фаза 1: Подготовка (Pre-Patching)
1.  **Сбор фактов и свидетельств:** Запись текущих версий ядра и критических пакетов.
2.  **Проверка готовности:** Контроль свободного места на диске (минимум 2 ГБ для `/var`) и отсутствия битых пакетов.
3.  **Создание точек отката:** Использование модулей облачных платформ или виртуализации (например, `community.vmware.vmware_guest_snapshot`) для создания мгновенных снимков системного диска.
4.  **Уведомление:** Оповещение команд мониторинга о начале работ для предотвращения ложных срабатываний (Silence).

### Фаза 2: Исполнение (Patching)
Применение обновлений с использованием стратегий конкурентности (`serial`, `throttle`) и фильтрации по категориям безопасности.

### Фаза 3: Верификация (Post-Patching)
1.  **Контрольная перезагрузка:** Выполнение только при необходимости.
2.  **Проверка здоровья (Health Checks):** Верификация доступности портов, ответов API и состояния системных юнитов.
3.  **Отчетность:** Генерация списка обновленных пакетов для целей комплаенса.

## Стратегии массового обновления

### 1. Последовательное обновление (`serial`)
Директива `serial` ограничивает количество хостов, обрабатываемых Ansible одновременно. Это основной инструмент для реализации Rolling Updates.

```yaml
- name: Обновление веб-серверов
  hosts: web_servers
  serial: "25%"  # Обновление по четверти серверов за раз
  tasks:
    - name: Обновление всех пакетов
      ansible.builtin.package:
        name: "*"
        state: latest
```
# → Ansible обновляет первую группу, и только при успехе переходит к следующей.

**Варианты настройки `serial`:**
*   `serial: 1` — строгая последовательность (Canary-стиль для первого хоста).
*   `serial: [1, 5, 20%]` — прогрессивная стратегия: сначала 1 хост, затем 5, затем 20% от остатка.
*   `any_errors_fatal: true` — при ошибке на любом хосте выполнение всего плейбука немедленно прекращается (критично для Canary).

### 2. Ограничение конкурентности задач (`throttle`)
В отличие от `serial`, который работает на уровне всего плея, `throttle` ограничивает количество одновременных выполнений конкретной задачи.

```yaml
- name: Регистрация в балансировщике
  ansible.builtin.uri:
    url: https://api.lb.example.com/register
  throttle: 1  # Только одно обращение к API за раз, чтобы не перегрузить его
```

### 3. Асинхронные обновления (`async`)
Используются для длительных операций (например, полное обновление ОС или пересборка ядра), которые могут превысить таймаут SSH-сессии.

```yaml
- name: Запуск долгого обновления ОС
  ansible.builtin.command: yum update -y
  async: 3600  # Максимальное время выполнения — 1 час
  poll: 0      # Режим "запустил и забыл"
  register: update_job

- name: Проверка статуса выполнения
  ansible.builtin.async_status:
    jid: "{{ update_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 30
  delay: 60
```

## Целевое обновление безопасности

В 2025-2026 годах рекомендуется отдавать приоритет обновлениям безопасности, а не обновлять все пакеты до `latest` без разбора.

### RHEL / Rocky / AlmaLinux
Используйте модуль `dnf` с параметром `security`.
```yaml
- name: Установка только security-патчей
  ansible.builtin.dnf:
    name: "*"
    security: yes
    state: latest
```

### Ubuntu / Debian
Для управления безопасностью рекомендуется использовать `unattended-upgrades` или точечное обновление через `apt`.
```yaml
- name: Обновление кеша и установка только обновлений безопасности
  ansible.builtin.apt:
    upgrade: dist
    update_cache: yes
    only_upgrade: yes
```

### Windows
Для Windows-инфраструктуры используется специализированный модуль.
```yaml
- name: Установка критических обновлений Windows
  ansible.windows.win_updates:
    category_names:
      - SecurityUpdates
      - CriticalUpdates
    reboot: yes  # Автоматическая перезагрузка только при необходимости
```

## Умная перезагрузка (Conditional Reboot)

Безусловная перезагрузка — плохая практика. Ansible позволяет проверять необходимость рестарта.

### Реализация для Debian/Ubuntu
Проверяется наличие файла-маркера.
```yaml
- name: Проверка необходимости перезагрузки (Debian)
  ansible.builtin.stat:
    path: /var/run/reboot-required
  register: reboot_required_file

- name: Перезагрузка Linux
  ansible.builtin.reboot:
    msg: "Reboot initiated by Ansible after patching"
  when: reboot_required_file.stat.exists
```

### Реализация для RHEL/Rocky
Используется утилита `needs-restarting`.
```yaml
- name: Проверка необходимости перезагрузки (RHEL)
  ansible.builtin.command: needs-restarting -r
  register: result
  failed_when: false
  changed_when: result.rc != 0

- name: Перезагрузка RHEL
  ansible.builtin.reboot:
  when: result.rc != 0
```

## Практические сценарии

### Сценарий 1: Комплексный кроссплатформенный Workflow
Безопасное обновление с предварительными проверками и Canary-тестированием.

```yaml
---
- name: Корпоративный стандарт патчинга 2026
  hosts: servers
  become: true
  serial: [1, "100%"]
  any_errors_fatal: true

  tasks:
    # --- Фаза 1: Pre-patching ---
    - name: Проверка свободного места в /var
      ansible.builtin.assert:
        that: ansible_facts['mounts'] | selectattr('mount', 'equalto', '/var') | map(attribute='size_available') | first > 2000000000
        msg: "Недостаточно места для обновлений"

    # --- Фаза 2: Patching ---
    - name: Обновление Linux (Debian)
      ansible.builtin.apt:
        upgrade: dist
        update_cache: yes
      when: ansible_facts['os_family'] == "Debian"
      register: apt_res

    - name: Обновление Linux (RedHat)
      ansible.builtin.dnf:
        name: "*"
        security: yes
        state: latest
      when: ansible_facts['os_family'] == "RedHat"
      register: dnf_res

    # --- Фаза 3: Post-patching & Reboot ---
    - name: Перезагрузка при необходимости
      ansible.builtin.reboot:
      when: 
        - (ansible_facts['os_family'] == "RedHat" and dnf_res.changed) or
          (ansible_facts['os_family'] == "Debian" and apt_res.changed)

    - name: Верификация работы приложения
      ansible.builtin.uri:
        url: "http://localhost:8080/health"
        status_code: 200
      register: health_check
      until: health_check.status == 200
      retries: 5
      delay: 10
```

## Дополнительная информация

- [Модули управления системой](./Modules/ansible_service_and_system_config_modules.md) — детали параметров `ansible.builtin.reboot`.
- [Кроссплатформенные концепции](./CrossPlatform/concepts.md) — глубокое погружение в разделение логики по ОС.
- [Оптимизация производительности](./ansible_performance_tuning.md) — настройка `forks` и `ssh_pipelining` для ускорения массового патчинга.
- [Выполнение плейбука: база](./PlaybookStructure/basics.md) — основы работы с `serial` и `tags`.
- [Управление ходом выполнения](./PlaybookStructure/flow_control.md) — использование `block` и `rescue` для обработки ошибок обновления.
