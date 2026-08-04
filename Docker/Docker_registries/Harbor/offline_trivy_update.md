# Harbor: Оффлайн-обновление баз Trivy

## Определения

* **Trivy**: Сканер уязвимостей для контейнеров и других артефактов. Использует базы данных уязвимостей (Trivy DB и Java DB) для идентификации CVE в образах.
* **Оффлайн-режим (Air-gapped)**: Режим работы системы в изолированной среде без прямого доступа к интернету. Требует ручной загрузки и доставки обновлений.
* **ORAS (OCI Registry As Storage)**: CLI-инструмент для работы с OCI-артефактами (включая базы Trivy), позволяющий скачивать файлы напрямую без использования Docker-демона.
* **Trivy DB (v2)**: Основная база данных уязвимостей, содержащая сведения о пакетах ОС и зависимостях приложений.
* **Trivy Java DB**: Специализированная база данных для анализа уязвимостей в Java-библиотеках.

## Основные концепции

Сканер Trivy в составе Harbor требует регулярного обновления баз для обнаружения актуальных угроз. В изолированных средах автоматическое обновление невозможно, поэтому применяется процедура ручной синхронизации.

### Жизненный цикл обновления

1.  **Загрузка**: Получение актуальных баз из GitHub Container Registry (GHCR) на хосте с интернетом.
2.  **Извлечение**: Распаковка баз из OCI-артефактов в виде файлов (обычно `trivy.db` и `metadata.json`).
3.  **Транспортировка**: Перенос архивов во внутренний контур.
4.  **Развертывание**: Размещение файлов в директории данных Harbor с корректными правами доступа.
5.  **Валидация**: Проверка статуса сканера в интерфейсе Harbor.

**Периодичность:** Рекомендуется обновлять базы не реже одного раза в неделю.

## Практические сценарии

### Сценарий 1: Подготовка баз с использованием ORAS (Рекомендуется)

Использование `oras` является наиболее современным и быстрым способом, так как оно не требует запуска контейнеров.

```bash
# 1. Скачивание баз
oras pull ghcr.io/aquasecurity/trivy-db:2
oras pull ghcr.io/aquasecurity/trivy-java-db:1

# 2. Проверка скачанных файлов
# Должны появиться файлы: db.tar.gz и javadb.tar.gz

# 3. Подготовка архива для переноса
mkdir -p trivy-offline && cd trivy-offline
mv ../db.tar.gz ../javadb.tar.gz .
tar -czf trivy-update-bundle.tgz *
```

### Сценарий 2: Подготовка баз через Docker (Legacy)

Если `oras` недоступен, можно использовать стандартный Docker.

```bash
# 1. Загрузка образов
docker pull ghcr.io/aquasecurity/trivy-db:2
docker pull ghcr.io/aquasecurity/trivy-java-db:1

# 2. Извлечение файлов через временный контейнер
docker run --rm -v $(pwd):/out ghcr.io/aquasecurity/trivy-db:2 cp /db/trivy.db /db/metadata.json /out/
docker run --rm -v $(pwd):/out ghcr.io/aquasecurity/trivy-java-db:1 cp /java-db/trivy-java.db /java-db/metadata.json /out/

# 3. Упаковка
tar -czf trivy-db.tgz trivy.db metadata.json
tar -czf trivy-java-db.tgz trivy-java.db metadata.json
```

### Сценарий 3: Обновление баз на сервере Harbor

1.  Перенесите архивы на сервер Harbor.
2.  Распакуйте файлы в директории `trivy-adapter`. Пути зависят от `data_volume` в `harbor.yml` (по умолчанию `/data`).

```bash
# Пути для Harbor на Docker Compose
DB_DIR="/data/trivy-adapter/trivy/db"
JAVA_DB_DIR="/data/trivy-adapter/trivy/java-db"

sudo mkdir -p $DB_DIR $JAVA_DB_DIR

# Распаковка (пример для файлов из Сценария 2)
sudo tar -xzf trivy-db.tgz -C $DB_DIR
sudo tar -xzf trivy-java-db.tgz -C $JAVA_DB_DIR

# УСТАНОВКА ПРАВ (Критически важно!)
# Пользователь внутри контейнера имеет UID 10000
sudo chown -R 10000:10000 /data/trivy-adapter/trivy
sudo chmod -R 755 /data/trivy-adapter/trivy
```

3.  Перезапустите сервис:
```bash
docker restart trivy-adapter
```

## Дополнительная информация

### Настройка конфигурации harbor.yml

Для предотвращения попыток Harbor выйти в интернет за обновлениями, установите следующие параметры:

```yaml
trivy:
  skip_update: true
  skip_java_db_update: true
  offline_scan: true
```

После редактирования выполните: `sudo ./prepare && docker compose up -d`.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `database error: schema mismatch` | Версия базы (v2) не совпадает с версией Trivy | Обновите Harbor до версии, поддерживающей Trivy DB v2. |
| `permission denied` | Неверный владелец файлов на хосте | Выполните `chown -R 10000:10000` на директорию данных. |
| `scan fails: metadata.json missing` | Не перенесен файл метаданных | Файл `metadata.json` обязателен для работы сканера. |

### Связанные документы

* **[Установка Harbor](./installation.md)** — развертывание в закрытых контурах.
* **[Обзор Harbor](./overview.md)** — архитектура Trivy-адаптера.
* **[Сканирование уязвимостей](../../Docker_security/vulnerability_scanning.md)** — методология анализа CVE.
