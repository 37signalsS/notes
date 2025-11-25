# Установка Prometheus (Практическое руководство)

Этот документ содержит пошаговую инструкцию по установке и настройке Prometheus на сервере под управлением Linux.

## Шаг 1: Создание пользователя

Для запуска Prometheus не требуются root-привилегии, поэтому с точки зрения безопасности лучше запускать его от непривилегированного пользователя.

```bash
useradd prometheus --comment "Prometheus server user" --shell /bin/false
```

## Шаг 2: Загрузка и установка

Скачиваем архив с бинарными файлами Prometheus и распаковываем его. В данном примере используется версия 2.24.1. Актуальный список версий можно найти на [странице релизов GitHub](https://github.com/prometheus/prometheus/releases).

```bash
cd /tmp
wget https://github.com/prometheus/prometheus/releases/download/v2.24.1/prometheus-2.24.1.linux-amd64.tar.gz
tar xvfz prometheus-2.24.1.linux-amd64.tar.gz
cd prometheus-2.24.1.linux-amd64
mv prometheus /usr/local/bin/
```

## Шаг 3: Настройка конфигурационных каталогов

Создаем каталог для конфигурационных файлов, копируем туда файл конфигурации по умолчанию и выставляем правильные права.

```bash
mkdir /etc/prometheus
cp prometheus.yml /etc/prometheus/
chown -R prometheus:prometheus /etc/prometheus
```

## Шаг 4: Создание каталога для базы данных

Создаем каталог, где Prometheus будет хранить свою базу данных временных рядов (TSDB).

```bash
mkdir /var/lib/prometheus
chown prometheus:prometheus /var/lib/prometheus
```

## Шаг 5: Создание файла с опциями запуска

Чтобы избежать необходимости постоянно редактировать systemd-юнит, ключи запуска выносятся в отдельный файл.

```bash
cat <<EOF > /etc/sysconfig/prometheus
OPTIONS="--config.file=/etc/prometheus/prometheus.yml \
--storage.tsdb.path=/var/lib/prometheus/"
EOF
```
*   `--config.file`: Указывает путь к основному конфигурационному файлу.
*   `--storage.tsdb.path`: Указывает путь к каталогу для хранения данных TSDB.

## Шаг 6: Создание systemd-сервиса

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
Директива `EnvironmentFile` позволяет подгружать переменные (в нашем случае `$OPTIONS`) из указанного файла.

## Шаг 7: Запуск Prometheus

Обновляем конфигурацию `systemd` и запускаем сервис.

```bash
systemctl daemon-reload
systemctl start prometheus
systemctl enable prometheus
```

## Шаг 8: Проверка работы

По умолчанию Prometheus слушает порт `9090`. Проверить доступность можно с помощью `curl` или открыв в браузере `http://<IP_сервера>:9090/graph`.

```bash
curl -XGET -IL http://localhost:9090/graph
```
Ответ должен быть `HTTP/1.1 200 OK`.

## Шаг 9: Утилита `promtool`

В состав Prometheus входит утилита `promtool` для проверки конфигурационных файлов. Это хорошая практика — проверять конфигурацию после каждого изменения.

```bash
# Копируем утилиту в /usr/local/bin для удобства
cp promtool /usr/local/bin/

# Проверяем конфигурационный файл
promtool check config /etc/prometheus/prometheus.yml 
```

---
**Связанные темы:**
*   [[./overview.md]]
*   [[./prometheus_setup_guide.md]]
*   [[./configuration_details.md]]
