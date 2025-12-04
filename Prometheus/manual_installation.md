# Руководство по ручной установке: Prometheus и Экспортеры

Этот документ содержит пошаговую инструкцию по ручной установке из бинарных файлов и настройке в качестве `systemd` сервисов для Prometheus и его ключевых компонентов: `node_exporter` и `blackbox_exporter`.

---

## 1. Установка Prometheus Server

### Шаг 1.1: Создание пользователя

Для запуска Prometheus не требуются root-привилегии, поэтому с точки зрения безопасности лучше запускать его от непривилегированного пользователя.

```bash
useradd prometheus --comment "Prometheus server user" --shell /bin/false
```

### Шаг 1.2: Загрузка и установка

Скачиваем архив с бинарными файлами Prometheus и распаковываем его. В данном примере используется версия 2.24.1. Актуальный список версий можно найти на [странице релизов GitHub](https://github.com/prometheus/prometheus/releases).

```bash
cd /tmp
wget https://github.com/prometheus/prometheus/releases/download/v2.24.1/prometheus-2.24.1.linux-amd64.tar.gz
tar xvfz prometheus-2.24.1.linux-amd64.tar.gz
cd prometheus-2.24.1.linux-amd64
mv prometheus promtool /usr/local/bin/
```

### Шаг 1.3: Настройка конфигурационных каталогов

Создаем каталог для конфигурационных файлов, копируем туда файл конфигурации по умолчанию и выставляем правильные права.

```bash
mkdir /etc/prometheus
cp prometheus.yml /etc/prometheus/
chown -R prometheus:prometheus /etc/prometheus
```

### Шаг 1.4: Создание каталога для базы данных

Создаем каталог, где Prometheus будет хранить свою базу данных временных рядов (TSDB).

```bash
mkdir /var/lib/prometheus
chown prometheus:prometheus /var/lib/prometheus
```

### Шаг 1.5: Создание файла с опциями запуска

Чтобы избежать необходимости постоянно редактировать systemd-юнит, ключи запуска выносятся в отдельный файл.

```bash
cat <<EOF > /etc/sysconfig/prometheus
OPTIONS="--config.file=/etc/prometheus/prometheus.yml \
--storage.tsdb.path=/var/lib/prometheus/"
EOF
```

### Шаг 1.6: Создание systemd-сервиса

Создаем unit-файл для управления Prometheus через `systemd`.

```bash
cat <<EOF > /usr/lib/systemd/system/prometheus.service 
[Unit]
Description=Prometheus Server
Documentation=https://github.com/prometheus/prometheus

[Service]
Restart=always
User=prometheus
Group=prometheus
EnvironmentFile=/etc/sysconfig/prometheus
ExecStart=/usr/local/bin/prometheus $OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
TimeoutStopSec=20s
SendSIGKILL=no

[Install]
WantedBy=multi-user.target
EOF
```

### Шаг 1.7: Запуск и проверка

```bash
systemctl daemon-reload
systemctl start prometheus
systemctl enable prometheus
curl -XGET -IL http://localhost:9090/graph # Ответ должен быть HTTP/1.1 200 OK
```

### Шаг 1.8: Утилита `promtool`

Проверяем конфигурационный файл с помощью утилиты `promtool`, которая была установлена на шаге 1.2.

```bash
promtool check config /etc/prometheus/prometheus.yml 
```

---

## 2. Установка Node Exporter

Практика выполняется с root-привилегиями.

### Шаг 2.1: Скачиваем и устанавливаем

```bash
cd /tmp
# Пример для версии 0.18.1. Актуальную версию можно найти на GitHub.
wget https://github.com/prometheus/node_exporter/releases/download/v0.18.1/node_exporter-0.18.1.linux-amd64.tar.gz
tar xvfz node_exporter-0.18.1.linux-amd64.tar.gz
mv node_exporter-0.18.1.linux-amd64/node_exporter /usr/local/bin/
```

### Шаг 2.2: Создаем файл для опций запуска

```bash
cat <<EOF > /etc/sysconfig/node_exporter
OPTIONS=""
EOF
```

### Шаг 2.3: Создаем systemd-сервис

> `node_exporter` требует root-привилегий для доступа к некоторым системным файлам.

```bash
cat <<EOF > /usr/lib/systemd/system/node_exporter.service 
[Unit]
Description=Prometheus Node exporter for machine metrics
Documentation=https://github.com/prometheus/node_exporter

[Service]
Restart=always
User=root
EnvironmentFile=/etc/sysconfig/node_exporter
ExecStart=/usr/local/bin/node_exporter $OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
TimeoutStopSec=20s
SendSIGKILL=no

[Install]
WantedBy=multi-user.target
EOF
```

### Шаг 2.4: Запускаем и проверяем

```bash
systemctl daemon-reload
systemctl start node_exporter
systemctl enable node_exporter
curl -I http://localhost:9100 # Ответ должен быть HTTP/1.1 200 OK
```

---

## 3. Установка Blackbox Exporter

### Шаг 3.1: Скачиваем и устанавливаем

```bash
cd /tmp
# Пример для версии 0.18.0. Актуальную версию можно найти на GitHub.
wget https://github.com/prometheus/blackbox_exporter/releases/download/v0.18.0/blackbox_exporter-0.18.0.linux-amd64.tar.gz 
tar xvfz blackbox_exporter-0.18.0.linux-amd64.tar.gz
mv blackbox_exporter-0.18.0.linux-amd64/blackbox_exporter /usr/local/bin/
```

### Шаг 3.2: Создаем конфигурацию

```bash
mkdir /etc/blackbox_exporter
# Копируем файл blackbox.yml из архива или создаем свой
cp blackbox_exporter-0.18.0.linux-amd64/blackbox.yml /etc/blackbox_exporter/
```

### Шаг 3.3: Создаем файл опций и systemd-сервис

```bash
# /etc/sysconfig/blackbox_exporter
cat <<EOF > /etc/sysconfig/blackbox_exporter
OPTIONS="--config.file=/etc/blackbox_exporter/blackbox.yml"
EOF

# /usr/lib/systemd/system/blackbox_exporter.service
cat <<EOF > /usr/lib/systemd/system/blackbox_exporter.service
[Unit]
Description=Prometheus Blackbox Exporter
Documentation=https://github.com/prometheus/blackbox_exporter

[Service]
Restart=always
# Пользователя создавать не нужно, можно использовать 'nobody'
User=nobody
Group=nobody
EnvironmentFile=/etc/sysconfig/blackbox_exporter
ExecStart=/usr/local/bin/blackbox_exporter $OPTIONS
ExecReload=/bin/kill -HUP $MAINPID

[Install]
WantedBy=multi-user.target
EOF
```

### Шаг 3.4: Запускаем и проверяем
```bash
systemctl daemon-reload
systemctl start blackbox_exporter
systemctl enable blackbox_exporter
curl -I http://localhost:9115 # Ответ должен быть HTTP/1.1 200 OK
```

---
**Связанные темы:**
*   [[./overview.md]]
*   [[./prometheus_setup_guide.md]]
*   [[./prometheus_configuration.md]]
*   [[./exporters.md]]

---


## 4. Установка Alertmanager


Это практическое руководство по установке выполняется на сервере мониторинга с root-привилегиями. 


### Шаг 4.1: Создание пользователя `alertmanager`

```bash

useradd --comment "User to run Alertmanager" --shell /bin/false alertmanager 

```



### Шаг 4.2: Скачивание и распаковка архива

Используется версия `0.21.0`. Список актуальных версий можно посмотреть на [странице GitHub](https://github.com/prometheus/alertmanager/releases).

```bash

cd /tmp

wget https://github.com/prometheus/alertmanager/releases/download/v0.21.0/alertmanager-0.21.0.linux-amd64.tar.gz

tar xvfz alertmanager-0.21.0.linux-amd64.tar.gz

cd alertmanager-0.21.0.linux-amd64

mv alertmanager /usr/local/bin/

```



### Шаг 4.3: Создание каталогов и копирование конфигурации

```bash

mkdir /etc/alertmanager          
cp alertmanager.yml /etc/alertmanager/alertmanager.yml 
chown alertmanager:alertmanager -R /etc/alertmanager
mkdir /var/lib/alertmanager/
chown alertmanager:alertmanager /var/lib/alertmanager/  
```



### Шаг 4.4: Создание файла с опциями запуска

```bash

cat <<EOF > /etc/sysconfig/alertmanager
OPTIONS="--config.file=/etc/alertmanager/alertmanager.yml \
  --storage.path=/var/lib/alertmanager/"
EOF
```



### Шаг 4.5: Создание systemd-сервиса

```bash

cat <<EOF > /usr/lib/systemd/system/alertmanager.service 
[Unit]
Description=Prometheus Alertmanager
[Service]
User=alertmanager
Group=alertmanager
Restart=always
EnvironmentFile=/etc/sysconfig/alertmanager
ExecStart=/usr/local/bin/alertmanager $OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
[Install]
WantedBy=multi-user.target
EOF
```



### Шаг 4.6: Запуск Alertmanager

```bash

systemctl daemon-reload

systemctl start alertmanager.service

systemctl enable alertmanager.service
```
---


## 5. Установка Pushgateway

Процесс установки аналогичен установке Prometheus.

### Шаг 5.1: Создание пользователя

```bash
useradd pushgateway --comment "Pushgateway server user" --shell /bin/false 
```

### Шаг 5.2: Загрузка и установка

Скачиваем архив с последней версией Pushgateway. В примере используется `v1.4.0`. Актуальные версии можно найти на [странице релизов](https://github.com/prometheus/pushgateway/releases).

```bash
cd /tmp
wget https://github.com/prometheus/pushgateway/releases/download/v1.4.0/pushgateway-1.4.0.linux-amd64.tar.gz
tar xvfz pushgateway-1.4.0.linux-amd64.tar.gz
cd pushgateway-1.4.0.linux-amd64
mv pushgateway /usr/local/bin/
```

### Шаг 5.3: Настройка опций запуска

```bash
cat <<EOF > /etc/sysconfig/pushgateway
OPTIONS="--web.listen-address=:9091 \
    --web.telemetry-path=/metrics \
    --persistence.file=/tmp/metric.store \
    --persistence.interval=5m \
    --log.level=info"
EOF
```

### Шаг 5.4: Создание systemd-сервиса

```bash
cat <<EOF > /usr/lib/systemd/system/pushgateway.service 
[Unit]
Description=Prometheus Pushgateway
Documentation=https://github.com/prometheus/pushgateway

[Service]
User=pushgateway
Group=pushgateway
EnvironmentFile=/etc/sysconfig/pushgateway
Restart=always
ExecStart=/usr/local/bin/pushgateway $OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
TimeoutStopSec=20s
SendSIGKILL=no

[Install]
WantedBy=multi-user.target
EOF
```

### Шаг 5.5: Запуск и проверка

```bash
systemctl daemon-reload
systemctl start pushgateway
systemctl enable pushgateway

# Проверяем доступность
curl -XGET -IL http://localhost:9091
```