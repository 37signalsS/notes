# Harbor: Установка

## Определения

* **Docker Compose**: Инструмент для определения и запуска многоконтейнерных приложений Docker. Используется для установки Harbor на отдельном хосте.
* **Helm**: Менеджер пакетов для Kubernetes, упрощающий развертывание сложных приложений через чарты (наборы манифестов).
* **Оффлайн-установка (Air-gapped)**: Развертывание в изолированной среде без доступа к интернету. Требует предварительной загрузки артефактов и настройки локальных репозиториев.

## Основные концепции

Harbor поддерживает два основных способа развертывания:

| Способ | Назначение | Требования |
| :--- | :--- | :--- |
| **Docker Compose** | Тестовые среды, небольшие продакшен-развертывания | Один хост с Docker, доменное имя или IP |
| **Helm (Kubernetes)** | Продакшен-среды, масштабируемые кластеры | Kubernetes-кластер, внешние БД и кэш (рекомендуется) |

**Ключевые требования для обоих способов:**

* **TLS-сертификаты**: Все клиенты должны доверять сертификату Harbor. См. [создание CA и сертификатов](./certificates.md).
* **Доменное имя**: `hostname` должен совпадать с CN/SAN в сертификате.
* **Пароли**: Храните в защищённом месте (`.env` с правами `600`, Kubernetes Secrets).

**Оффлайн-режим:** Для закрытых контуров без доступа к интернету конфигурация Trivy требует дополнительных настроек (`skip_update: true`, `offline_scan: true`). Обновление баз уязвимостей выполняется вручную (см. [оффлайн-обновление Trivy](./offline_trivy_update.md)).

## Практические сценарии

### Сценарий 1: Установка Harbor с Docker Compose

#### 1. Установка Docker и Docker Compose

Для работы Harbor требуется установленный Docker Engine и плагин Docker Compose.

> **Полная инструкция:** см. SSoT-файл **[Установка Docker на Ubuntu](../../docker_install_ubuntu.md)**.

#### 2. Загрузка Harbor

```bash
# Загрузка оффлайн-установщика последней версии
LATEST=$(curl -s https://api.github.com/repos/goharbor/harbor/releases/latest \
  | grep browser_download_url | grep offline-installer | cut -d '"' -f 4)

FILE=$(basename "$LATEST")
wget "$LATEST"
# → Saving to: ‘harbor-offline-installer-v2.x.x.tgz’

tar xvzf "$FILE"
# → harbor/
# → harbor/harbor.yml.tmpl
# → harbor/install.sh
# → ...

rm "$FILE"
cd harbor
```

#### 3. Настройка переменных окружения

Создайте файл `.env` с паролями для подстановки в конфигурацию:

```bash
sudo nano .env
```

```ini
HARBOR_ADMIN_PASSWORD=<надёжный_пароль_администратора>
DB_PASSWORD=<надёжный_пароль_БД>
```

Установите права доступа (только для текущего пользователя):

```bash
sudo chmod 600 .env
# → (no output)
```

#### 4. Настройка harbor.yml

Создайте рабочий файл конфигурации из шаблона:

```bash
cp harbor.yml.tmpl harbor.yml
sudo nano harbor.yml
```

**Пример минимальной конфигурации (версия 2.14.x):**

```yaml
hostname: harbor.example.local
http:
  port: 80
https:
  port: 443
  certificate: /opt/harbor/harbor.example.local.crt
  private_key: /opt/harbor/harbor.example.local.key
# Использование переменных из .env в harbor.yml не поддерживается напрямую скриптом install.sh,
# поэтому укажите значения явно или используйте envsubst перед запуском.
harbor_admin_password: "admin_password_here"
database:
  password: "db_password_here"
data_volume: /data
trivy:
  skip_update: true
  offline_scan: true
# ... остальные параметры ...
```

**Важно:** Перед запуском убедитесь, что сертификаты созданы и размещены в директории, указанной в `https.certificate` и `https.private_key` (см. [создание сертификатов](./certificates.md)).

#### 5. Запуск установки

Скрипт выполнит проверку системы, загрузит образы и запустит контейнеры.

```bash
sudo ./install.sh --with-trivy
# → [Step 0]: checking if docker is installed ...
# → [Step 1]: checking docker-compose is installed ...
# → ...
# → [Step 5]: starting Harbor ...
# → Creating harbor-log ... done
# → ...
# → ✔ ----Harbor has been installed and started successfully.----
```

#### 6. Вход в веб-интерфейс

Откройте `https://harbor.example.local` в браузере.

* **Логин:** `admin`
* **Пароль:** значение, указанное в `harbor_admin_password`

---

### Сценарий 2: Установка Harbor в Kubernetes через Helm

#### Предварительные требования

* Kubernetes-кластер (v1.25+)
* Установленный [Helm](https://helm.sh/) (v3.10+)
* Установленный [cert-manager](../../../Kubernetes/ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) (опционально)
* Внешние PostgreSQL и Redis (рекомендуется для высокодоступных сред)

#### 1. Подготовка базы данных

Если используется внешний PostgreSQL, создайте базу данных для Harbor:

```sql
CREATE DATABASE harbor;
# → CREATE DATABASE
```

#### 2. Добавление репозитория Helm

Рекомендуется использовать чарты от **Bitnami**:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
# → "bitnami" has been added to your repositories

helm repo update
# → Hang tight while we grab the latest from your chart repositories...
# → ...Successfully got an update from the "bitnami" chart repository
```

#### 3. Конфигурация и развертывание через ArgoCD

Пример манифеста `Application` для GitOps-подхода:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: harbor
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://charts.bitnami.com/bitnami'
    chart: harbor
    targetRevision: 19.3.x # Используйте актуальную версию чарта
    helm:
      values: |
        harborAdminPassword: "<смените_после_установки>"
        expose:
          type: ingress
          tls:
            enabled: true
            secretName: harbor-tls
          ingress:
            hostname: registry.example.com
            annotations:
              cert-manager.io/cluster-issuer: "letsencrypt-prod"
        persistence:
          enabled: true
          registry:
            size: 50Gi
        postgresql:
          enabled: false
        externalDatabase:
          host: "postgres-host"
          # ...
```

**Результат:** После синхронизации ArgoCD развернет Harbor в кластере. Статус приложения изменится на `Synced`.

## Дополнительная информация

### Архитектура с внешними зависимостями

Для продакшен-сред рекомендуется использовать внешние сервисы:

* **PostgreSQL**: Централизованное управление БД, резервное копирование, настройка производительности. См. [PostgreSQL overview](../../../Databases/PostgreSQL/overview.md).
* **Redis**: Внешний кэш для сессий и очередей. См. [Redis overview](../../../Databases/redis_overview.md).

### Безопасность

* **Пароли в values.yaml**: Некоторые чарты требуют указания паролей в открытом виде. По возможности используйте чарты с поддержкой Kubernetes Secrets.
* **TLS-сертификаты**: Для публичных сервисов используйте доверенные CA (Let's Encrypt). Для внутренних — собственный CA (см. [certificates.md](./certificates.md)).

### Связанные документы

[Обзор Harbor](./overview.md) описывает возможности и назначение. [Создание сертификатов](./certificates.md) — создание CA и серверных сертификатов. [Работа с Harbor](./usage.md) — аутентификация, тегирование, push/pull. [Оффлайн-обновление Trivy](./offline_trivy_update.md) — обновление баз уязвимостей.
