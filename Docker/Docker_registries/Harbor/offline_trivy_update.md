# Harbor: Оффлайн-обновление баз Trivy

## Определения

* **Trivy**: Сканер уязвимостей для контейнеров и других артефактов. Использует базы данных уязвимостей (Trivy DB и Java DB) для идентификации CVE в образах.
* **Оффлайн-режим (Air-gapped)**: Режим работы системы в изолированной среде без прямого доступа к интернету. Требует ручной загрузки и доставки обновлений.
* **Trivy DB**: Основная база данных уязвимостей, содержащая сведения о пакетах ОС и зависимостях приложений.
* **Trivy Java DB**: Специализированная база данных для анализа уязвимостей в Java-библиотеках.

## Основные концепции

Сканер Trivy в составе Harbor требует регулярного обновления баз для обнаружения актуальных угроз. В изолированных средах автоматическое обновление невозможно, поэтому применяется процедура ручной синхронизации:

1.  Загрузка актуальных баз на хосте с доступом в интернет.
2.  Извлечение файлов баз из OCI-артефактов (образов).
3.  Перенос архивов на изолированный сервер Harbor.
4.  Обновление файлов в директории данных Trivy-адаптера.
5.  Перезапуск сервиса для инициализации новых данных.

**Периодичность:** Рекомендуется выполнять обновление не реже одного раза в неделю.

**Требования:**

* Хост с доступом к интернету и установленным Docker.
* Доступ к серверу Harbor с правами sudo.
* Способ переноса файлов (USB, SCP через промежуточный хост).

## Практические сценарии

### 1. Подготовка баз на машине с интернетом

Загрузите актуальные образы баз уязвимостей из GitHub Container Registry:

```bash
# Загрузка основной базы (версия v2 является актуальной)
docker pull ghcr.io/aquasecurity/trivy-db:2

# Загрузка базы для Java
docker pull ghcr.io/aquasecurity/trivy-java-db:1
```

Извлеките файлы баз из контейнеров:

```bash
# Извлечение Trivy DB
cid=$(docker create ghcr.io/aquasecurity/trivy-db:2)
docker cp $cid:/db ./db
docker rm $cid

# Извлечение Java DB
cid=$(docker create ghcr.io/aquasecurity/trivy-java-db:1)
docker cp $cid:/java-db ./java-db
docker rm $cid
```

Упакуйте данные для переноса:

```bash
tar czf trivy-db.tgz db
tar czf trivy-java-db.tgz java-db
```

### 2. Установка баз на сервере Harbor

Перенесите файлы `trivy-db.tgz` и `trivy-java-db.tgz` в закрытый контур.

Распакуйте архивы в рабочую директорию Trivy (пути по умолчанию для Harbor):

```bash
# Создание структуры директорий
sudo mkdir -p /data/trivy-adapter/trivy/db
sudo mkdir -p /data/trivy-adapter/trivy/java-db

# Распаковка с очисткой путей
sudo tar -xzf trivy-db.tgz -C /data/trivy-adapter/trivy/db --strip-components=1
sudo tar -xzf trivy-java-db.tgz -C /data/trivy-adapter/trivy/java-db --strip-components=1

# Установка прав доступа (ID 10000 соответствует пользователю trivy внутри контейнера)
sudo chown -R 10000:10000 /data/trivy-adapter/trivy
```

Примените изменения, перезапустив компонент:

```bash
docker restart trivy-adapter
```

Проверьте логи на предмет успешной загрузки баз:

```bash
docker logs trivy-adapter | grep -i "database"
# → "msg":"Sever-side update of Trivy database is skipped"
# → "msg":"Trivy database is up to date"
```

## Дополнительная информация

### Настройка конфигурации Harbor

Для корректной работы в закрытом контуре в файле `harbor.yml` должны быть установлены соответствующие флаги:

```yaml
trivy:
  skip_update: true           # Запрет обновления основной базы
  skip_java_db_update: true    # Запрет обновления Java-базы
  offline_scan: true          # Включение режима оффлайн-сканирования
```

После изменения конфигурации необходимо перезапустить Harbor:
`sudo ./prepare && docker compose up -d`

### Проверка в интерфейсе

Статус баз можно отследить в веб-интерфейсе: **Administration → Interrogation Services**. В разделе **Vulnerability Scanning** должна обновиться дата в поле **Last Update** для Trivy.

### Автоматизация процесса

При наличии "полуоткрытого" контура (доступ через jump-host) рекомендуется использовать скрипт на базе `rsync` для синхронизации содержимого директории `/data/trivy-adapter/trivy/` с доверенным источником.

### Связанные документы

* **[Установка Harbor](./installation.md)** — развертывание и базовая конфигурация.
* **[Обзор Harbor](./overview.md)** — архитектура и возможности компонентов.
* **[Сканирование уязвимостей](../../Docker_security/vulnerability_scanning.md)** — общие принципы работы со сканерами безопасности.
