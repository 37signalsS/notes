# Обзор Helm

Helm — пакетный менеджер для Kubernetes, автоматизирующий параметризацию, версионирование и управление жизненным циклом приложений.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Чарт (Chart)** | Пакет с преднастроенными ресурсами Kubernetes. См. [Структура Helm-чарта](./helm_chart_structure.md) для деталей организации файлов |
| **Релиз (Release)** | Экземпляр чарта, развёрнутый в кластере с уникальным именем в пределах namespace. Подробнее о версионировании см. [Управление версиями релизов](./helm_release_versioning.md) |
| **Репозиторий (Repository)** | HTTP-сервер или OCI-реестр для хранения и распространения чартов |
| **Значения (Values)** | Параметры конфигурации, передаваемые в шаблоны через `values.yaml` или `--set`. См. [Шаблонизация в Helm](./helm_templating.md) |

---

## Основные концепции

### Пакетный подход к развёртыванию

Helm объединяет приложение, инфраструктурные манифесты и зависимости в единый версионированный артефакт — чарт.

**Преимущества подхода:**

| Аспект | Обычные манифесты (kubectl) | Пакетный подход (Helm) |
|--------|------------------------------|------------------------|
| **Единица поставки** | Набор файлов без версии | Чарт с версией |
| **Параметризация** | Ограниченная, вручную | Шаблоны и values |
| **Зависимости** | Управляются отдельно | Субчарты и lock-файл |
| **Откат изменений** | Требует ручного восстановления | Исторический rollback |
| **Публикация** | Git-репозиторий | Репозиторий чартов / OCI-реестр |

**Ключевые возможности:**

- **Повторяемость**: Один чарт разворачивается во всех окружениях с переопределением параметров через `values`
- **Версионирование**: Связь между версиями чарта и приложения (`version` и `appVersion` в Chart.yaml). Подробнее см. [Управление версиями релизов](./helm_release_versioning.md)
- **Управление зависимостями**: Базы данных, кэши, ingress-контроллеры как субчарты. См. [Зависимости и Library Charts](./helm_dependencies_and_library_charts.md)
- **Атомарные операции**: Обновления с автоматическим откатом при сбое (`--atomic`)
- **История релизов**: Хранение состояний и диффов для аудита и откатов
- **Конфигурационная изоляция**: Разные окружения через отдельные `values`-файлы без дублирования шаблонов

### Архитектура Helm 3

Helm 3 работает по клиент-only модели без серверного компонента. Детальное сравнение с Helm v2 см. в [Сравнение Helm v2 и v3](./helm_v2_vs_v3.md).

**Особенности архитектуры:**

- Клиент напрямую взаимодействует с Kubernetes API через kubeconfig пользователя
- Хранение истории релизов в Secrets в namespace релиза (не ConfigMaps в kube-system как в v2)
- Нативная интеграция с RBAC Kubernetes
- Тристороннее слияние (three-way merge) при обновлениях

### Шаблонизация манифестов

Helm использует Go template engine с библиотекой Sprig для генерации манифестов. Полная документация — в разделе [Шаблонизация в Helm](./helm_templating.md).

**Встроенные объекты:**

- `.Values` — значения из `values.yaml` и флагов `--set`
- `.Release` — метаданные релиза (имя, namespace, ревизия)
- `.Chart` — метаданные чарта из `Chart.yaml`
- `.Capabilities` — возможности кластера (версия API, доступные ресурсы)
- `.Files` — доступ к файлам чарта

---

## Установка CLI

### Способ 1: Установочный скрипт (рекомендуемый)

```bash
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod 700 get_helm.sh
./get_helm.sh
```

### Способ 2: Ручная установка

```bash
# Скачайте архив с https://github.com/helm/helm/releases
tar -zxvf helm-v3.14.0-linux-amd64.tar.gz
sudo mv linux-amd64/helm /usr/local/bin/helm
helm version
```

## Практические сценарии

### Жизненный цикл релиза

```bash
# 1. Добавление репозитория
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# 2. Поиск чартов
helm search repo nginx

# 3. Установка релиза
helm install myapp bitnami/nginx -n production

# 4. Просмотр статуса
helm status myapp -n production

# 5. Обновление релиза
helm upgrade myapp bitnami/nginx -n production

# 6. Просмотр истории
helm history myapp -n production

# 7. Откат к предыдущей версии
helm rollback myapp 1 -n production

# 8. Удаление релиза
helm uninstall myapp -n production
```

### Многоокружная стратегия

```bash
# Структура values-файлов:
# chart/
#   values.yaml         # базовые значения
#   values-dev.yaml     # переопределения для dev
#   values-staging.yaml # переопределения для staging
#   values-prod.yaml    # переопределения для prod

# Dev окружение
helm install app ./chart -f values-dev.yaml -n dev

# Staging окружение
helm install app ./chart -f values-staging.yaml -n staging

# Production окружение (с атомарностью и ожиданием)
helm install app ./chart -f values-prod.yaml -n prod --atomic --wait --timeout 10m
```

### Установка конкретной версии

```bash
# Из репозитория с указанием версии чарта
helm install myapp bitnami/nginx --version 13.2.0 -n prod

# С ограничением истории
helm install myapp ./mychart --atomic --history-max 20 -n prod
```

### Отладка и тестирование

```bash
# Локальный рендер шаблонов
helm template myapp ./chart -f values.yaml

# Проверка с подключением к кластеру
helm install --dry-run --debug myapp ./chart -f values.yaml

# Линтинг чарта
helm lint ./chart
```

### Работа с OCI-реестрами

Современный стандарт публикации чартов — OCI-реестры (Docker Registry, GHCR, Harbor).

```bash
# Публикация чарта в OCI-реестр
helm package ./mychart
helm push mychart-1.0.0.tgz oci://registry.example.com/charts

# Установка из OCI-реестра
helm install myapp oci://registry.example.com/charts/mychart --version 1.0.0

# Логин в OCI-реестр
helm registry login registry.example.com -u username -p password
```

**Преимущества OCI перед HTTP-репозиториями:**

- Единый интерфейс для контейнеров и чартов
- Встроенная аутентификация и авторизация
- Поддержка подписей и верификации
- Интеграция с CI/CD через docker login

---

## Дополнительная информация

- [Структура Helm-чарта](./helm_chart_structure.md) — файловая организация, Chart.yaml, values.yaml
- [Шаблонизация в Helm](./helm_templating.md) — Go templates, встроенные объекты, функции Sprig
- [Управление версиями релизов](./helm_release_versioning.md) — версионирование, ревизии, откаты
- [Сравнение Helm v2 и v3](./helm_v2_vs_v3.md) — архитектурные различия, миграция
- [Основные команды и рабочий процесс](./helm_commands_and_workflow.md) — практическое руководство
