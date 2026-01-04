# Мониторинг PostgreSQL с помощью Prometheus и Ansible

## Определения

**Мониторинг PostgreSQL с помощью Prometheus и Ansible** — это процесс автоматизированного развертывания и настройки полного стека мониторинга для базы данных PostgreSQL. Ansible используется для управления конфигурацией, `postgres_exporter` — для сбора метрик, а Prometheus — для их агрегации и хранения.

## Основные концепции

-   **Компоненты стека мониторинга**:
    -   **[PostgreSQL](../../Databases/PostgreSQL/overview.md)**: Объект мониторинга, реляционная СУБД.
    -   **[Prometheus PostgreSQL Exporter](https://github.com/prometheus-community/postgres_exporter)**: Специализированный сервис (экспортер), который запускается рядом с базой данных. Он выполняет запросы к PostgreSQL для сбора статистики (например, количество активных соединений, скорость транзакций) и предоставляет их по HTTP в формате, понятном для Prometheus.
    -   **[Prometheus](../../Prometheus/overview.md)**: Система мониторинга, которая периодически опрашивает (scrape) HTTP-ендпоинт экспортера, собирает метрики и сохраняет их в свою базу данных временных рядов.

-   **Автоматизация с [Ansible](../../Ansible/ansible_introduction.md)**:
    -   **Готовые роли Ansible Galaxy**: Чтобы не писать логику установки и настройки с нуля, используются проверенные сообществом роли: `community.postgresql` для PostgreSQL, `prometheus-community.postgres_exporter` для экспорtera, и `cloudalchemy.prometheus` для Prometheus.
    -   **Защита секретов**: Чувствительные данные, такие как пароли от базы данных для экспортера, должны быть зашифрованы с помощью [Ansible Vault](../../Ansible/ansible_vault.md).

## Практические сценарии

### Сценарий: Настройка полного стека мониторинга

#### Шаг 1: Структура инвентаря и переменных

**Файл инвентаря `hosts.ini`:**
```ini
[postgres_servers]
pg01 ansible_host=192.168.55.10

[monitoring_servers]
mon01 ansible_host=192.168.55.20
```

**Переменные и секреты:**
Переменные для ролей удобно хранить в `group_vars`.

`group_vars/postgres_servers.yml`:
```yaml
# Переменные для роли community.postgresql
postgresql_databases:
  - name: myapp_db
postgresql_users:
  - name: myapp_user
    pass: "{{ db_password }}" # Пароль будет взят из Vault
```

`group_vars/all.yml` (шифруется с помощью Vault):
```yaml
# ansible-vault encrypt group_vars/all.yml
db_password: "MySuperSecretPassword"
```

#### Шаг 2: Плейбук для PostgreSQL и Exporter

Этот play устанавливает СУБД, создает пользователя для мониторинга и настраивает экспортер.

```yaml
- name: Setup PostgreSQL and Exporter
  hosts: postgres_servers
  become: true
  
  vars:
    # Строка подключения для экспортера
    postgres_exporter_dsn: "postgresql://{{ postgresql_users[0].name }}:{{ db_password }}@localhost:5432/{{ postgresql_databases[0].name }}?sslmode=disable"

  roles:
    # 1. Устанавливаем PostgreSQL
    - role: community.postgresql
      vars:
        # Настраиваем PostgreSQL для прослушивания всех интерфейсов
        postgresql_conf:
          - name: listen_addresses
            value: '*'
        # Разрешаем подключение по паролю для всех
        postgresql_hba_entries:
          - { type: host, database: all, user: all, address: '0.0.0.0/0', method: md5 }

    # 2. Устанавливаем и настраиваем экспортер
    - role: prometheus-community.postgres_exporter
      vars:
        # Передаем строку подключения через переменную окружения
        postgres_exporter_environment_vars:
          DATA_SOURCE_NAME: "{{ postgres_exporter_dsn }}"

  post_tasks:
    - name: Healthcheck for postgres_exporter
      ansible.builtin.uri:
        url: "http://localhost:9187/metrics"
        return_content: yes
      register: metrics_page
      until: "'pg_up 1' in metrics_page.content"
      retries: 5
      delay: 10
```

#### Шаг 3: Плейбук для Prometheus

Этот play разворачивает Prometheus на сервере мониторинга и настраивает его на сбор метрик с `postgres_exporter`.

```yaml
- name: Setup Prometheus
  hosts: monitoring_servers
  become: true

  roles:
    - role: cloudalchemy.prometheus
      vars:
        # Добавляем новую задачу для сбора метрик с PostgreSQL
        prometheus_scrape_configs:
          - job_name: 'postgres'
            static_configs:
              - targets:
                  # Явно указываем хосты из группы postgres_servers
                  - "{{ hostvars[item]['ansible_host'] }}:9187"
                with_items: "{{ groups['postgres_servers'] }}"
```

## Дополнительная информация

### Проверка статуса в Prometheus

После выполнения плейбуков откройте веб-интерфейс Prometheus по адресу `http://<monitoring_server_ip>:9090`. Перейдите в раздел **Status → Targets**. Вы должны увидеть эндпоинт вашего `postgres_exporter` (например, `192.168.55.10:9187`) со статусом **UP**. Это означает, что Prometheus успешно собирает метрики.