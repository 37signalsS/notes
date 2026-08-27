# Стратегии деплоя и rolling updates в Ansible

## Определения

- **Rolling Update** — поэтапное обновление группы серверов с контролем здоровья между этапами
- **Canary Deployment** — развёртывание на малой подгруппе хостов для тестирования перед полным обновлением
- **Blue-Green Deployment** — параллельное существование двух идентичных сред (Blue и Green) с переключением трафика
- **Health Check** — проверка доступности сервиса после изменений для подтверждения успеха
- **max_fail_percentage** — максимальный допустимый процент ошибок в батче перед прерыванием
- **Serial** — параметр плейбука, определяющий размер батча хостов
- **Drain** — процесс отключения хоста от балансировщика перед обновлением
- **Strategy plugin** — плагин, определяющий алгоритм распределения задач (linear, free, debug)

## Основные концепции

### Rolling Updates

Параметры управления поэтапным обновлением:

```yaml
---
- name: Rolling Update Example
  hosts: webservers
  serial: "25%"              # 25% хостов за раз
  max_fail_percentage: 10    # Допустимо до 10% ошибок
  strategy: linear
  tasks:
    - name: Обновление пакетов
      ansible.builtin.apt:
        name: "*"
        state: latest
        update_cache: true

    - name: Перезапуск сервиса
      ansible.builtin.service:
        name: nginx
        state: restarted

    - name: Проверка здоровья
      ansible.builtin.uri:
        url: "http://localhost/health"
        status_code: 200
      retries: 5
      delay: 5
```

**Порядок执行:** 25% хостов → health check → следующие 25% → ...

### Health Checks

```yaml
# Использование uri для проверки HTTP
- name: Проверка HTTP
  ansible.builtin.uri:
    url: "http://{{ ansible_host }}:{{ http_port }}/health"
    status_code: 200
  register: health
  retries: 10
  delay: 5
  until: health.status == 200

# Проверка TCP-порта
- name: Проверка порта
  ansible.builtin.wait_for:
    port: "{{ http_port }}"
    delay: 5
    timeout: 30
```

### Rollback стратегии

```yaml
---
- name: Deploy with Rollback
  hosts: webservers
  tasks:
    - name: Блок с откатом
      block:
        - name: Развёртывание новой версии
          ansible.builtin.copy:
            src: "app_v{{ new_version }}/"
            dest: /opt/app/

        - name: Перезапуск сервиса
          ansible.builtin.service:
            name: myapp
            state: restarted

        - name: Проверка здоровья
          ansible.builtin.uri:
            url: http://localhost:8080/health
            status_code: 200
          register: health_check
          retries: 5
          delay: 10
          until: health_check.status == 200

      rescue:
        - name: Откат на предыдущую версию
          ansible.builtin.copy:
            src: "app_v{{ previous_version }}/"
            dest: /opt/app/

        - name: Перезапуск предыдущей версии
          ansible.builtin.service:
            name: myapp
            state: restarted
```

### Zero-downtime

```yaml
# Drain перед обновлением
- name: Отключение от балансировщика
  ansible.builtin.uri:
    url: "http://{{ lb_host }}/api/drain/{{ inventory_hostname }}"
    method: POST
  delegate_to: localhost

# Обновление
- name: Обновление сервера
  ansible.builtin.apt:
    name: nginx
    state: latest

# Включение на балансировщике
- name: Включение на балансировщике
  ansible.builtin.uri:
    url: "http://{{ lb_host }}/api/enable/{{ inventory_hostname }}"
    method: POST
  delegate_to: localhost
```

### Blue-Green Deployment

```yaml
---
- name: Blue-Green Deployment
  hosts: localhost
  vars:
    active_env: blue
    target_env: green
  tasks:
    - name: Определение активной среды
      ansible.builtin.set_fact:
        active_group: "{{ 'webservers_blue' if active_env == 'blue' else 'webservers_green' }}"
        target_group: "{{ 'webservers_green' if active_env == 'blue' else 'webservers_blue' }}"

    - name: Развёртывание на target
      ansible.builtin.include_role:
        name: deploy_app
      vars:
        target_hosts: "{{ target_group }}"

    - name: Health check target
      ansible.builtin.uri:
        url: "http://{{ hostvars[groups[target_group][0]]['ansible_host'] }}/health"
        status_code: 200
      register: target_health
      retries: 10
      delay: 5
      until: target_health.status == 200

    - name: Переключение трафика
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/switch/{{ target_env }}"
        method: POST
      when: target_health.status == 200
```

### Кастомные Strategy Plugins

```yaml
# Free strategy — каждый хост движется максимально быстро
- name: Free Strategy Example
  hosts: webservers
  strategy: free
  tasks:
    - name: Долгая задача
      ansible.builtin.command: /opt/scripts/long_task.sh
    - name: Быстрая задача
      ansible.builtin.ping:
```

## Практические сценарии

### Rolling Update Nginx с Health Check

```yaml
---
- name: Rolling Update Nginx
  hosts: webservers
  serial: 1
  max_fail_percentage: 0
  tasks:
    - name: Отключение от балансировщика
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/disable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost
      ignore_errors: true

    - name: Ожидание завершения активных соединений
      ansible.builtin.command: sleep 30

    - name: Обновление Nginx
      ansible.builtin.apt:
        name: nginx
        state: latest
        update_cache: true

    - name: Перезапуск Nginx
      ansible.builtin.service:
        name: nginx
        state: restarted

    - name: Health check
      ansible.builtin.uri:
        url: "http://{{ ansible_host }}/health"
        status_code: 200
      register: health
      retries: 10
      delay: 5
      until: health.status == 200

    - name: Включение на балансировщике
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/enable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost
      when: health.status == 200
```

### Percentage-based Batches

```yaml
---
- name: Percentage-based Rolling Update
  hosts: all
  serial: "10%"
  max_fail_percentage: 5
  tasks:
    - name: Обновление пакетов
      ansible.builtin.yum:
        name: "*"
        state: latest
      when: ansible_os_family == "RedHat"

    - name: Обновление пакетов (Debian)
      ansible.builtin.apt:
        name: "*"
        state: latest
        update_cache: true
      when: ansible_os_family == "Debian"

    - name: Перезапуск сервиса
      ansible.builtin.service:
        name: "{{ service_name }}"
        state: restarted
```

### Canary Deployment

```yaml
---
- name: Canary Deployment
  hosts: webservers
  serial: 1
  tasks:
    - name: Развёртывание на canary (1 хост)
      ansible.builtin.include_tasks: deploy.yml
      when: inventory_hostname == groups['webservers'][0]

    - name: Мониторинг canary
      ansible.builtin.uri:
        url: "http://{{ ansible_host }}/metrics"
        return_content: true
      register: canary_metrics
      until: "'error_rate' in canary_metrics.content and canary_metrics.content.split('error_rate')[1].split()[0]|float < 0.01"
      retries: 30
      delay: 10
      when: inventory_hostname == groups['webservers'][0]

    - name: Развёртывание на остальные хосты
      ansible.builtin.include_tasks: deploy.yml
      when: inventory_hostname != groups['webservers'][0]
```

## Дополнительная информация

- [Производительность](./ansible_performance_tuning.md) — оптимизация выполнения плейбуков
- [Выполнение плейбуков](./ansible_playbook_execution.md) — режимы запуска
- [Продвинутая структура плейбуков](./PlaybookStructure/advanced.md) — сложные сценарии