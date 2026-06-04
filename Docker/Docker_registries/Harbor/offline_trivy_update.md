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

Установите Docker (если не установлен), следуя **[инструкции](../../docker_install_ubuntu.md)**.

Загрузите актуальные образы баз уязвимостей из GitHub Container Registry:

```bash
docker pull ghcr.io/aquasecurity/trivy-db:2
docker pull ghcr.io/aquasecurity/trivy-java-db:1
# → 2: Pulling from aquasecurity/trivy-db
# → Digest: sha256:...
# → Status: Downloaded newer image for ghcr.io/aquasecurity/trivy-db:2
```

Извлеките файлы баз из временных контейнеров:

```bash
# Trivy DB (основная база)
cid=$(docker create ghcr.io/aquasecurity/trivy-db:2)
docker cp $cid:/db db
docker rm $cid
# → db/trivy.db, db/metadata.json

# Java DB (база для Java-зависимостей)
cid=$(docker create ghcr.io/aquasecurity/trivy-java-db:1)
docker cp $cid:/java-db java-db
docker rm $cid
# → java-db/trivy-java.db, java-db/metadata.json
```

Упакуйте базы для переноса в закрытый контур:

```bash
tar czf trivy-db.tgz db
tar czf trivy-java-db.tgz java-db
# → trivy-db.tgz, trivy-java-db.tgz
```

### 2. Перенос и установка баз на Harbor-хост

Перенесите архивы на хост Harbor любым доступным способом (USB, SCP, WinSCP).

Распакуйте базы в директорию данных Trivy-адаптера (путь по умолчанию для Harbor):

```bash
# Создание структуры директорий (если отсутствуют)
sudo mkdir -p /data/trivy-adapter/trivy/db
sudo mkdir -p /data/trivy-adapter/trivy/java-db

# Распаковка с заменой старых файлов
sudo tar -xzf trivy-db.tgz -C /data/trivy-adapter/trivy/db --strip-components=1
sudo tar -xzf trivy-java-db.tgz -C /data/trivy-adapter/trivy/java-db --strip-components=1

# Установка прав доступа (ID 10000 соответствует пользователю trivy в контейнере)
sudo chown -R 10000:10000 /data/trivy-adapter/trivy
# → (no output)
```

Перезапустите компонент `trivy-adapter` для применения изменений:

```bash
docker restart trivy-adapter
# → trivy-adapter
```

Проверьте логи на предмет успешной инициализации баз:

```bash
docker logs trivy-adapter --tail 50
# → ... "msg":"Sever-side update of Trivy database is skipped"
# → ... "msg":"Trivy database is up to date"
```

## Дополнительная информация

### Конфигурация Harbor для оффлайн-режима

В файле `harbor.yml` должны быть жестко заданы параметры, запрещающие Trivy попытки выхода в интернет:

```yaml
trivy:
  skip_update: true           # Пропускать обновление основной базы
  skip_java_db_update: true    # Пропускать обновление Java базы
  offline_scan: true          # Режим сканирования без интернета
```

После правки `harbor.yml` необходимо применить конфигурацию:
`sudo ./prepare && docker compose up -d`

Подробности см. в [установке Harbor](./installation.md).

### Проверка статуса в UI

После обновления баз статус сканера в веб-интерфейсе Harbor должен измениться:

1. Перейдите в **Administration → Interrogation Services**.
2. В секции **Vulnerability Scanning** проверьте дату **Last Update** для Trivy.

### Автоматизация

Для регулярного обновления в условиях "периодического" доступа к сети (например, через jump-host) рекомендуется использовать скрипт:

```bash
#!/bin/bash
# Пример: /usr/local/bin/update-trivy-offline.sh
# 1. Pull images
# 2. Extract to /tmp/trivy-update
# 3. Rsync to harbor-host:/data/trivy-adapter/trivy/
```

### Связанные документы

* **[Установка Harbor](./installation.md)** — общая настройка компонентов.
* **[Обзор Harbor](./overview.md)** — возможности и архитектура реестра.
* **[Сканирование уязвимостей](../../Docker_security/vulnerability_scanning.md)** — общие принципы SCA и CVE.
