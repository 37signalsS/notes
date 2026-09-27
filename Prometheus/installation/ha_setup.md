# Высокая доступность (HA) Prometheus: практическое развертывание

## Определения

**High Availability (HA)** — архитектура, при которой два или более экземпляра Prometheus независимо опрашивают одни и те же цели, гарантируя непрерывность сбора метрик при падении одного из них.

**Дедупликация** — механизм удаления дублирующихся алертов. При HA-паре Prometheus оба сервера генерируют идентичные алерты. Alertmanager получает дубликаты и отправляет только одно уведомление.

**External Labels** — метки (например, `prometheus_replica`), добавляемые к данным каждого экземпляра, позволяющие различать идентичные метрики и выполнять дедупликацию.

> **См. также:** [Концепции HA](../concepts/high_availability.md) — теоретические основы; [Установка Alertmanager](./alertmanager_installation.md) — базовая установка; [Масштабирование](../scaling/overview.md) — архитектурные альтернативы.

## Основные концепции

### Принцип работы HA Prometheus

```
                    ┌──────────────────┐
                    │   Alertmanager   │
                    │   Cluster (3)    │
                    └────────▲─────────┘
                             │ alerting
              ┌──────────────┴──────────────┐
              │                              │
     ┌────────┴────────┐          ┌─────────┴────────┐
     │  Prometheus 1   │          │  Prometheus 2    │
     │  (replica=a)    │          │  (replica=b)     │
     └────────▲────────┘          └─────────▲────────┘
              │ scrape                       │ scrape
              └──────────┬───────────────────┘
                         │
              ┌──────────┴──────────┐
              │   Цели (Targets)    │
              │  (Node Exporters)   │
              └─────────────────────┘
```

**Ключевые принципы:**

1. **Идентичная конфигурация:** Оба Prometheus получают одинаковый `prometheus.yml`.
2. **Независимость TSDB:** Экземпляры НЕ синхронизируют данные. При падении одного данные за этот период есть только в другом.
3. **Уникальные External Labels:** Каждый экземпляр получает свою метку `prometheus_replica` для дедупликации.
4. **Alertmanager кластер:** Алерты отправляются во все экземпляры Alertmanager, которые дедуплицируют через Gossip.

### Когда нужен HA

| Сценарий | HA нужен? | Почему |
|---|---|---|
| Dev/test среда | Нет | Достаточно одного инстанса |
| Production < 100 серверов | Желателен | Простой failover |
| Production > 100 серверов | Обязателен | Потеря метрик = потеря видимости |
| Мульти-ДЦ | Обязателен + LTS | Данные не должны теряться при outage ДЦ |

### Модели HA

| Модель | Описание | Когда использовать |
|---|---|---|
| **Два Prometheus + Alertmanager cluster** | Классический bare-metal подход | До ~500K active series |
| **Agent Mode + Remote Write** | Легковесные агенты, LTS хранит данные | Edge-кластеры, > 500K series |
| **Thanos/VictoriaMetrics** | Внешний слой дедупликации | Крупные production среды |

## Практические сценарии

### Сценарий 1: HA на bare-metal (2 Prometheus + 3 Alertmanager)

#### Шаг 1: Два экземпляра Prometheus

Установите Prometheus на два сервера (или два процесса на одном для тестирования). Используйте идентичный конфиг, различая только `external_labels`:

**Prometheus 1 (`/etc/prometheus/prometheus.yml`):**

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: 'production'
    prometheus_replica: 'prom-1'    # Уникальная метка для этого экземпляра

rule_files:
  - 'alerting_rules.yml'

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager-1:9093'
            - 'alertmanager-2:9093'
            - 'alertmanager-3:9093'

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node'
    static_configs:
      - targets:
          - 'server-1:9100'
          - 'server-2:9100'
          - 'server-3:9100'
```

**Prometheus 2 (`/etc/prometheus/prometheus.yml`):**

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: 'production'
    prometheus_replica: 'prom-2'    # Другая метка!

rule_files:
  - 'alerting_rules.yml'

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager-1:9093'
            - 'alertmanager-2:9093'
            - 'alertmanager-3:9093'

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node'
    static_configs:
      - targets:
          - 'server-1:9100'
          - 'server-2:9100'
          - 'server-3:9100'
```

> **Важно:** Единственное различие — `prometheus_replica`. Всё остальное идентично.

#### Шаг 2: Alertmanager кластер (3 узла)

На каждом из трех серверов установите Alertmanager с общим конфигом и кластерными параметрами:

**`/etc/alertmanager/alertmanager.yml` (общий для всех 3 узлов):**

```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'slack-notifications'

receivers:
  - name: 'slack-notifications'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'
        channel: '#alerts'
        send_resolved: true
```

**Systemd unit для Alertmanager 1 (`/etc/systemd/system/alertmanager.service`):**

```ini
[Unit]
Description=Prometheus Alertmanager
After=network-online.target

[Service]
User=alertmanager
Group=alertmanager
Type=simple
ExecStart=/usr/local/bin/alertmanager \
    --config.file=/etc/alertmanager/alertmanager.yml \
    --storage.path=/var/lib/alertmanager/ \
    --web.listen-address=:9093 \
    --cluster.listen-address=10.0.0.11:9094 \
    --cluster.peer=10.0.0.12:9094 \
    --cluster.peer=10.0.0.13:9094
Restart=always
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Для Alertmanager 2:**

```ini
ExecStart=/usr/local/bin/alertmanager \
    --config.file=/etc/alertmanager/alertmanager.yml \
    --storage.path=/var/lib/alertmanager/ \
    --web.listen-address=:9093 \
    --cluster.listen-address=10.0.0.12:9094 \
    --cluster.peer=10.0.0.11:9094 \
    --cluster.peer=10.0.0.13:9094
```

**Для Alertmanager 3:**

```ini
ExecStart=/usr/local/bin/alertmanager \
    --config.file=/etc/alertmanager/alertmanager.yml \
    --storage.path=/var/lib/alertmanager/ \
    --web.listen-address=:9093 \
    --cluster.listen-address=10.0.0.13:9094 \
    --cluster.peer=10.0.0.11:9094 \
    --cluster.peer=10.0.0.12:9094
```

#### Шаг 3: Валидация кластера Alertmanager

```bash
# Проверка состояния кластера на любом узле
amtool cluster show --alertmanager.url=http://localhost:9093
# → CLUSTERADDR    PEERADDR       STATE    ...
# → 10.0.0.11:9094 10.0.0.12:9094 joined
# → 10.0.0.11:9094 10.0.0.13:9094 joined

# Проверка доступности
curl -s http://localhost:9093/-/healthy
# → OK
```

#### Шаг 4: Проверка дедупликации алертов

Создайте тестовый алерт, убедитесь, что приходит только одно уведомление:

```bash
# На Prometheus 1: создание тестового алерта
curl -X POST http://prom-1:9090/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '[{"labels":{"alertname":"TestHA","severity":"critical"}}]'

# На Prometheus 2: тот же алерт
curl -X POST http://prom-2:9090/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '[{"labels":{"alertname":"TestHA","severity":"critical"}}]'

# В Slack должно прийти ОДНО сообщение, а не два
```

#### Шаг 5: Порты и firewall

| Порт | Протокол | Назначение | Откуда доступен |
|---|---|---|---|
| `9090` | TCP | Prometheus Web UI / API | Grafana, jump-hosts |
| `9093` | TCP | Alertmanager Web UI / API | Prometheus, Grafana |
| `9094` | TCP+UDP | Alertmanager Gossip | Только реплики Alertmanager |
| `9100` | TCP | Node Exporter | Только Prometheus серверы |

```bash
# На Alertmanager-узлах: разрешить Gossip только между репликами
sudo iptables -A INPUT -p tcp --dport 9094 -s 10.0.0.11/32 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 9094 -s 10.0.0.12/32 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 9094 -s 10.0.0.13/32 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 9094 -s 10.0.0.11/32 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 9094 -s 10.0.0.12/32 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 9094 -s 10.0.0.13/32 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 9094 -j DROP
sudo iptables -A INPUT -p udp --dport 9094 -j DROP
```

### Сценарий 2: HA через Ansible (iplab-scale)

```yaml
---
- name: Развертывание HA Prometheus + Alertmanager
  hosts: monitoring
  become: yes
  vars:
    prometheus_version: "3.13.2"
    alertmanager_version: "0.33.1"
    alertmanager_cluster_peers:
      - "10.0.0.11:9094"
      - "10.0.0.12:9094"
      - "10.0.0.13:9094"

  tasks:
    - name: Установка Prometheus
      ansible.builtin.include_role:
        name: prometheus.prometheus.prometheus

    - name: Установка Alertmanager
      ansible.builtin.include_role:
        name: prometheus.prometheus.alertmanager

    - name: Настройка кластера Alertmanager
      ansible.builtin.lineinfile:
        path: /etc/systemd/system/alertmanager.service
        regexp: '--cluster.peer='
        line: >-
          --cluster.peer={{ item }}
      loop: "{{ alertmanager_cluster_peers | reject('search', ansible_default_ipv4.address) | list }}"
      notify: restart alertmanager

  handlers:
    - name: restart alertmanager
      ansible.builtin.systemd:
        name: alertmanager
        state: restarted
        daemon_reload: yes
```

## Диагностика

| Проблема | Причина | Решение |
|---|---|---|
| Alertmanager не формирует кластер | Порт 9094 заблокирован | Проверить `iptables -L -n \| grep 9094` и `amtool cluster show` |
| Дублирующиеся уведомления | `external_labels` не настроены | Добавить `prometheus_replica` в `global.external_labels` каждого Prometheus |
| Алерты не доходят | Alertmanager не запущен | `curl http://alertmanager:9093/-/healthy` |
| Split-brain в Alertmanager | Нечетное число узлов не соблюдено | Использовать минимум 3 узла, проверить сетевую связность |
| Prometheus 1 падает, данных нет | Нет LTS или federation | Настроить remote_write в Thanos/VictoriaMetrics |

## Рекомендации SRE

1. **Минимум 2 Prometheus + 3 Alertmanager** — стандартная HA-конфигурация для production.
2. **External Labels обязательны** — без них дедупликация невозможна.
3. **Идентичные конфиги** — распространяйте `prometheus.yml` через Git/Ansible, не редактируйте вручную на каждом сервере.
4. **Мониторьте сам HA** — настройте алерт на `up{job="prometheus"} == 0` для каждого экземпляра.
5. **Не используйте HA без LTS** — при падении Prometheus данные за этот период теряются навсегда.

## См. также

*   **[Концепции HA](../concepts/high_availability.md)** — теория Active-Active, дедупликация, WAL.
*   **[Federation](../scaling/federation.md)** — иерархическая агрегация метрик.
*   **[Thanos](../scaling/thanos_overview.md)** — долгосрочное хранение и глобальный view.
*   **[Remote Write](../scaling/remote_read_write.md)** — отправка данных во внешние хранилища.
*   **[Self-Monitoring](../self_monitoring.md)** — мониторинг самого Prometheus.
