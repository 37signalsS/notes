# Настройка Prometheus HA с помощью HAProxy

Этот документ описывает настройку высокодоступного (HA) кластера Prometheus с использованием HAProxy в качестве балансировщика нагрузки.

## 1. Установка и настройка Prometheus в режиме HA

Этот шаг необходимо выполнить на двух серверах (server1 и server2) для создания дублирующих экземпляров Prometheus.

### 1.1 Установка Prometheus

Установите Prometheus на серверы `server1` и `server2`. Инструкции по установке можно найти в документе [[../prometheus_installation.md]].

### 1.2 Настройка `prometheus.yml`

После установки на каждом из серверов Prometheus необходимо обновить конфигурационный файл. Эта конфигурация настраивает каждый экземпляр на сбор метрик с `node_exporter` на трех серверах (`monitoring`, `server1`, `server2`) и указывает `alertmanager` в качестве цели для алертов.

Перед выполнением команды замените `<monitoring_ip>`, `<server1_ip>` и `<server2_ip>` на реальные IP-адреса.

```bash
cat <<EOF > /etc/prometheus/prometheus.yml
global:
  scrape_interval:     15s 
  evaluation_interval: 15s 

alerting:
  alertmanagers:
  - static_configs:
    - targets:
      - alertmanager:9093

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
    - targets: ['localhost:9090']
  - job_name: 'node_exporter'
    static_configs:
    - targets:
        - <monitoring_ip>:9100
        - <server1_ip>:9100
        - <server2_ip>:9100
EOF
```

### 1.3 Перезапуск и проверка

Перезапустите Prometheus, чтобы применить настройки:
```bash
systemctl restart prometheus.service
```

Проверьте, что Prometheus работает на порту `9090`:
```bash
curl -XGET -IL http://localhost:9090/graph
```
Ответ должен быть `HTTP/1.1 200 OK`.

## 2. Настройка HAProxy

Для обеспечения отказоустойчивости доступа к экземплярам Prometheus со стороны Grafana, установим и настроим HAProxy на сервере `monitoring`.

### 2.1 Установка HAProxy
```bash
yum install -y haproxy
```

### 2.2 Настройка `haproxy.cfg`

Эта конфигурация настраивает HAProxy на проксирование запросов с порта `80` на один из серверов Prometheus. `server1` будет основным (`check`), а `server2` — резервным (`check backup`).

Перед выполнением команды замените `<server1_IP>` и `<server2_IP>` на реальные IP-адреса.

```bash
cat <<EOF > /etc/haproxy/haproxy.cfg 
#HA Proxy Config
global
 daemon
 maxconn 256
defaults
 mode http
 timeout connect 5000ms
 timeout client 50000ms
 timeout server 50000ms
listen stats
 bind *:9999
 stats enable
 stats hide-version
 stats uri /stats
 stats auth admin:admin@123
frontend prom
 bind *:80
 use_backend prom
backend prom
 server prom1 <server1_IP>:9090 check
 server prom2 <server2_IP>:9090 check backup
EOF
```

### 2.3 Запуск HAProxy
```bash
systemctl start haproxy.service
```

## 3. Настройка Grafana

### 3.1 Добавление Data Source

Добавьте новый источник данных (Data Source) в Grafana:
-   **Name**: `Prometheus HA`
-   **URL**: `http://localhost:80` (адрес HAProxy)

### 3.2 Добавление Dashboard

Импортируйте дашборд, например, с ID `1860`. При импорте **важно** в качестве источника данных (`Prometheus data source`) выбрать созданный ранее `Prometheus HA`.

## 4. Проверка отказоустойчивости

Для проверки, что HA-схема работает корректно, поочередно останавливайте сервис Prometheus на `server1` и `server2` и убедитесь, что графики в Grafana продолжают отображаться.

```bash
# На server1, затем на server2
systemctl stop prometheus.service
```
