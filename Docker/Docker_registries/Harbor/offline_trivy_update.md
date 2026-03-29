# Harbor: Оффлайн-обновление баз Trivy

## Определения

* **Trivy**: Сканер уязвимостей для контейнеров и других артефактов. Использует базы данных уязвимостей (Trivy DB и Java DB) для идентификации CVE в образах.
* **Оффлайн-режим (Air-gapped)**: Режим работы в изолированной среде без доступа к интернету. Требует ручной загрузки и обновления баз данных.
* **Trivy DB**: База данных уязвимостей для ОС-пакетов и зависимостей приложений.
* **Trivy Java DB**: База данных уязвимостей для Java-библиотек.

## Основные концепции

Сканер уязвимостей Trivy в Harbor требует регулярного обновления баз данных для обнаружения новых CVE. В закрытых контурах (без доступа к интернету) автоматическое обновление невозможно, поэтому применяется ручная процедура:

1. Загрузка актуальных образов баз с машины с доступом в интернет.
2. Извлечение файлов баз из образов.
3. Перенос файлов на изолированный хост Harbor.
4. Размещение файлов в директории Trivy-адаптера.
5. Перезапуск компонента `trivy-adapter`.

**Периодичность:** Рекомендуется обновлять базы не реже 1 раза в неделю или после публикации критических обновлений безопасности.

**Требования:**

* Машина с доступом к интернету и установленным Docker.
* Переносной носитель (USB-накопитель) или SCP-доступ для передачи файлов.
* Доступ к хосту Harbor с правами root/sudo.

## Практические сценарии

### 1. Подготовка баз на машине с доступом в интернет

Установите Docker (если не установлен):

```bash
apt update
apt install -y docker.io
systemctl enable --now docker
usermod -aG docker $USER
```

Загрузите образы баз уязвимостей:

```bash
docker pull ghcr.io/aquasecurity/trivy-db:2
docker pull ghcr.io/aquasecurity/trivy-java-db:1
```

Извлеките файлы баз из образов:

```bash
# Trivy DB
cid=$(docker create ghcr.io/aquasecurity/trivy-db:2)
docker cp $cid:/db db
docker rm $cid

# Java DB
cid=$(docker create ghcr.io/aquasecurity/trivy-java-db:1)
docker cp $cid:/java-db java-db
docker rm $cid
```

Упакуйте базы для переноса:

```bash
tar czf trivy-db.tgz db
tar czf trivy-java-db.tgz java-db
```

### 2. Перенос и установка баз на Harbor-хост

Перенесите файлы `trivy-db.tgz` и `trivy-java-db.tgz` на хост Harbor (через USB или SCP).

Распакуйте базы в директорию Trivy-адаптера:

```bash
sudo mkdir -p /data/trivy-adapter/trivy/db
sudo mkdir -p /data/trivy-adapter/trivy/java-db

sudo tar -xzf trivy-db.tgz -C /data/trivy-adapter/trivy/db
sudo tar -xzf trivy-java-db.tgz -C /data/trivy-adapter/trivy/java-db

# Установите правильные права (владелец trivy-adapter)
sudo chown -R 10000:10000 /data/trivy-adapter/trivy
```

Перезапустите Trivy-адаптер:

```bash
docker restart trivy-adapter
```

Проверьте логи на наличие ошибок:

```bash
docker logs trivy-adapter --tail 50
```

## Дополнительная информация

### Конфигурация Harbor для оффлайн-режима

В `harbor.yml` должны быть установлены следующие параметры Trivy:

```yaml
trivy:
  skip_update: true
  skip_java_db_update: true
  offline_scan: true
  insecure: false
```

Подробности см. в [установке Harbor](./installation.md).

### Автоматизация обновления

Для регулярного обновления создайте скрипт и планируйте его запуск через cron:

```bash
# /etc/cron.weekly/trivy-update
#!/bin/bash
# Скрипт загрузки и переноса баз Trivy
```

### Связанные документы

[Установка Harbor](./installation.md) описывает настройку Trivy для оффлайн-режима. [Обзор Harbor](./overview.md) содержит информацию о возможностях сканирования уязвимостей. [Сканирование уязвимостей](../../Docker_security/vulnerability_scanning.md) рассматривает общие принципы и инструменты.
