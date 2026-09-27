# Основные команды и рабочий процесс Helm

Полный жизненный цикл управления Helm-приложениями: от поиска чарта до установки, отладки, управления релизами в кластере и работы с OCI-реестрами. В версии **v4 (стандарт 2026 года)** фокус смещен на декларативность через Server-Side Apply и нативную поддержку OCI.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Релиз (Release)** | Развёрнутый экземпляр чарта в Kubernetes-кластере. В v4 управляется через SSA. См. [Управление версиями релизов](./helm_release_versioning.md). |
| **Ревизия (Revision)** | Порядковый номер версии релиза, увеличивающийся при каждом `upgrade` или `rollback`. |
| **Идемпотентность** | Свойство операции давать одинаковый результат при повторных вызовах (реализовано через `upgrade --install`). |
| **Server-Side Apply (SSA)** | Механизм Kubernetes (стандарт в Helm v4), при котором слияние манифестов происходит на стороне API-сервера. |
| **helm upgrade --install** | Универсальная команда: устанавливает новый релиз или обновляет существующий. |
| **helm template** | Локальный рендер шаблонов без обращения к кластеру. Основной инструмент отладки. |
| **helm lint** | Валидация чарта на синтаксические ошибки и соответствие лучшим практикам. |
| **OCI (Open Container Initiative)** | Стандарт хранения и дистрибуции чартов в контейнерных реестрах (Registry) как артефактов. |
| **helm diff** | Плагин, показывающий детальный diff между текущей и предстоящей ревизией перед upgrade. |

---

## Справочник команд

### 1. Работа с репозиториями (helm repo)

Репозитории — это каталоги чартов с `index.yaml`. В v4 рекомендуется переходить на OCI-реестры, но HTTP-репозитории по-прежнему поддерживаются.

| Команда | Описание | Пример |
|---------|----------|--------|
| `helm repo add <name> <url>` | Добавление репозитория | `helm repo add bitnami https://charts.bitnami.com/bitnami` |
| `helm repo update <name>` | Обновление кеша (или всех если без аргументов) | `helm repo update` |
| `helm repo list` | Просмотр добавленных репозиториев | `helm repo list` |
| `helm repo remove <name>` | Удаление репозитория | `helm repo remove bitnami` |

> **Важно:** `helm repo update` скачивает `index.yaml`, но не сами чарты. Чарты загружаются при `helm install` или `helm pull`.

### 2. Поиск чартов (helm search)

| Команда | Описание | Пример |
|---------|----------|--------|
| `helm search repo <keyword>` | Поиск в добавленных репозиториях | `helm search repo prometheus` |
| `helm search hub <keyword>` | Поиск на Artifact Hub ( hubs.artifacthub.io ) | `helm search hub kube-prometheus-stack` |
| `helm search repo <repo>/<chart> --version <ver>` | Поиск конкретной версии | `helm search repo bitnami/nginx --version 18.x` |
| `helm search repo <keyword> --devel` | Включить пре-релизы (alpha, beta, rc) | `helm search repo my-chart --devel` |

**Фильтрация и сортировка:**
```bash
# Вывод всех версий чарта
helm search repo bitnami/nginx -l

# Поиск с ограничением количества результатов
helm search repo prometheus --max-col-width 60
```

### 3. Инспектирование чартов (helm show / helm inspect)

| Команда | Описание |
|---------|----------|
| `helm show chart <chart>` | Метаданные чарта (name, version, description, dependencies) |
| `helm show values <chart>` | Содержимое `values.yaml` |
| `helm show readme <chart>` | README чарта (если есть) |
| `helm show crds <chart>` | CRD, определённые в директории `crds/` |
| `helm show all <chart>` | Все вышеперечисленное |

```bash
# Просмотр всех метаданных чарта
helm show all prometheus-community/kube-prometheus-stack

# Просмотр CRD перед установкой (критично для безопасности)
helm show crds bitnami/redis
```

**Отличие `show` от `inspect`:** `helm inspect` — это синоним `helm show` (устаревшее название, но всё ещё работает).

### 4. Скачивание чартов (helm pull / helm fetch)

| Команда | Описание |
|---------|----------|
| `helm pull <chart>` | Скачивание чарта в текущую директорию |
| `helm pull <chart> --untar` | Скачивание и автоматическая распаковка |
| `helm pull <chart> --destination <dir>` | Сохранение в указанную директорию |
| `helm pull <chart> --version <ver>` | Скачивание конкретной версии |
| `helm pull <chart> --prov` | Скачивание с файлом провенанса ( provenance ) |

```bash
# Скачивание и распаковка чарта для редактирования
helm pull bitnami/nginx --untar --version 18.0.0

# Скачивание из OCI-реестра
helm pull oci://registry.example.com/charts/my-app --version 1.0.0

# Сохранение в конкретную директорию
helm pull prometheus-community/kube-prometheus-stack --destination ./charts/ --untar
```

### 5. Управление зависимостями (helm dependency)

| Команда | Описание |
|---------|----------|
| `helm dependency update <chart-dir>` | Скачивание зависимостей и создание `Chart.lock` |
| `helm dependency build <chart-dir>` | Восстановление зависимостей из `Chart.lock` (без обновлений) |
| `helm dependency list <chart-dir>` | Просмотр текущих зависимостей и их статуса |

```bash
# Обновление зависимостей (скачивает актуальные версии)
helm dependency update ./my-chart

# Восстановление из lock-файла (для CI/CD)
helm dependency build ./my-chart

# Просмотр зависимостей и их статуса
helm dependency list ./my-chart
# NAME        VERSION   REPOSITORY                STATUS
# postgresql  15.x.x    oci://registry.example    ok
# redis       19.0.2    https://charts.bitnami    missing
```

### 6. Установка и обновление (helm install / helm upgrade)

| Команда | Описание |
|---------|----------|
| `helm install <name> <chart>` | Установка нового релиза |
| `helm install <name> <chart> -f <file>` | Установка с файлом значений |
| `helm install <name> <chart> --set key=value` | Установка с инлайн-значениями |
| `helm install <name> <chart> --generate-name` | Автоматическая генерация имени |
| `helm install <name> <chart> --namespace <ns> --create-namespace` | Установка с созданием namespace |
| `helm install <name> <chart> --atomic` | Атомарная установка (откат при ошибке) |
| `helm install <name> <chart> --wait` | Ожидание готовности всех ресурсов |
| `helm upgrade <name> <chart>` | Обновление существующего релиза |
| `helm upgrade --install <name> <chart>` | Идемпотентная установка/обновление (универсальная команда) |
| `helm upgrade <name> <chart> --reuse-values` | Переиспользование текущих значений (только override) |
| `helm upgrade <name> <chart> --reset-values` | Сброс к дефолтным values.yaml |
| `helm upgrade <name> <chart> --dependency-update` | Обновление зависимостей перед upgrade |
| `helm upgrade <name> <chart> --force` | Принудительное обновление (удаление + пересоздание) |
| `helm upgrade <name> <chart> --cleanup-on-fail` | Удаление ресурсов при ошибке |

**Флаги ожидания и атомарности (подробно):**

| Флаг | Описание | Доступен для |
|------|----------|-------------|
| `--timeout <duration>` | Время ожидания готовности (по умолчанию 5m). | `install`, `upgrade`, `rollback` |
| `--wait` | Ждёт готовности всех подов, PVC, Service (LoadBalancer IP) и CRD (через kstatus). | `install`, `upgrade`, `rollback` |
| `--atomic` | Включает `--wait` + автоматический `rollback` при сбое или таймауте. | `install`, `upgrade` |
| `--cleanup-on-fail` | Удаляет созданные ресурсы, если транзакция не удалась (предотвращает конфликты). | `install`, `upgrade` |
| `--server-side` | Явное включение SSA (в v4 активно по умолчанию). | `install`, `upgrade` |
| `--force-conflicts` | Перехват владения полями (field ownership) у других контроллеров. | `install`, `upgrade` |
| `--dependency-update` | Автоматическое обновление зависимостей перед деплоем. | `install`, `upgrade` |

**Порядок создания ресурсов (Kind Order):**

Helm создаёт ресурсы в строгой последовательности:

1. **Namespace**
2. **NetworkPolicy**, **ResourceQuota**, **LimitRange**
3. **ServiceAccount**, **Secret**, **ConfigMap**
4. **PersistentVolume**, **PersistentVolumeClaim**
5. **CustomResourceDefinition** (приоритетно из директории `crds/`)
6. **ClusterRole**, **Role** (и их Binding)
7. **Deployment**, **StatefulSet**, **DaemonSet**, **Job**
8. **Service**, **Ingress**
9. **APIService**

### 7. Управление релизами (helm list / helm status / helm history / helm get)

| Команда | Описание |
|---------|----------|
| `helm list` | Список всех релизов в текущем namespace |
| `helm list -A` | Список всех релизов во всех namespace |
| `helm list --filter <regex>` | Фильтрация по имени |
| `helm list --status <status>` | Фильтрация по статусу (deployed, failed, pending) |
| `helm list -o json` | Вывод в формате JSON |
| `helm status <release>` | Статус конкретного релиза |
| `helm status <release> -o yaml` | Статус в YAML формате |
| `helm history <release>` | История ревизий |
| `helm history <release> --max <n>` | Ограничение количества ревизий |
| `helm get values <release>` | Просмотр пользовательских значений |
| `helm get values <release> --all` | Все значения (включая defaults) |
| `helm get manifest <release>` | Просмотр применённых манифестов |
| `helm get notes <release>` | Просмотр инструкций из NOTES.txt |
| `helm get hooks <release>` | Просмотр определений хуков |
| `helm get all <release>` | Все данные релиза (values + manifest + hooks + notes) |

**Примеры фильтрации:**
```bash
# Все.failed релизы
helm list --status failed

# Релизы в конкретном namespace
helm list -n production

# Релизы с именем, соответствующим regex
helm list --filter "app-.*"

# JSON-вывод для парсинга скриптами
helm list -A -o json | jq '.[] | select(.status=="failed") | .name'
```

### 8. Откат и удаление (helm rollback / helm uninstall / helm delete)

| Команда | Описание |
|---------|----------|
| `helm rollback <release> <revision>` | Откат к конкретной ревизии |
| `helm rollback <release> <revision> --force` | Принудительный откат (удаление + пересоздание) |
| `helm rollback <release> <revision> --wait` | Ожидание готовности после отката |
| `helm rollback <release> <revision> --timeout <duration>` | Таймаут ожидания готовности |
| `helm uninstall <release>` | Удаление релиза и всех ресурсов |
| `helm uninstall <release> --keep-history` | Удаление ресурсов с сохранением истории |
| `helm uninstall <release> --namespace <ns>` | Удаление из указанного namespace |
| `helm uninstall <release> --no-hooks` | Удаление без выполнения хуков |
| `helm delete <release>` | Синоним `helm uninstall` |

**Удаление с сохранением истории:**
```bash
# Ресурсы удалены, но ревизии сохранены в Secret. Можно выполнить rollback.
helm uninstall myapp --keep-history
```

### 9. Тестирование (helm test)

| Команда | Описание |
|---------|----------|
| `helm test <release>` | Запуск тестов релиза |
| `helm test <release> --namespace <ns>` | Тесты в конкретном namespace |
| `helm test <release> --timeout <duration>` | Таймаут выполнения тестов |
| `helm test <release> --filter <regex>` | Запуск тестов по имени |
| `helm test <release> --logs` | Вывод логов Pod'ов тестов |

```bash
# Запуск всех тестов
helm test my-release -n production

# Запуск тестов с выводом логов
helm test my-release --logs

# Фильтрация тестов по имени
helm test my-release --filter "smoke"
```

> **Подробнее:** См. [Хуки и тестирование в Helm](./helm_hooks_and_tests.md).

### 10. Упаковка и публикация (helm package / helm push)

| Команда | Описание |
|---------|----------|
| `helm package <chart-dir>` | Упаковка чарта в `.tgz` файл |
| `helm push <chart>.tgz <repo>` | Публикация в HTTP-репозиторий |
| `helm push <chart>.tgz oci://<registry>` | Публикация в OCI-реестр |
| `helm verify <chart>.tgz` | Проверка подписи и провенанса |

```bash
# Упаковка
helm package ./my-chart
# → my-chart-1.2.3.tgz

# Публикация в OCI-реестр
helm push my-chart-1.2.3.tgz oci://registry.example.com/charts

# Публикация в ChartMuseum
helm push my-chart-1.2.3.tgz chartmuseum
```

### 11. OCI-реестры (helm registry)

| Команда | Описание |
|---------|----------|
| `helm registry login <host>` | Авторизация в OCI-реестре |
| `helm registry logout <host>` | Выход из OCI-реестра |

```bash
# Авторизация (требуется только домен)
helm registry login registry.example.com

# Авторизация с токеном
helm registry login registry.example.com --username admin --password-stdin < token.txt
```

**Полный OCI-workflow:**
```bash
# 1. Авторизация
helm registry login registry.example.com

# 2. Упаковка и публикация
helm package ./my-chart
helm push my-chart-1.2.3.tgz oci://registry.example.com/charts

# 3. Инспектирование и установка по дигесту (Immutable)
helm show values oci://registry.example.com/charts/my-chart --version 1.2.3
helm upgrade --install my-app oci://registry.example.com/charts/my-app@sha256:7f...
```

### 12. Отладка и локальный рендеринг (helm template / helm lint)

| Команда | Описание |
|---------|----------|
| `helm template <name> <chart>` | Локальный рендер без обращения к кластеру |
| `helm template <name> <chart> -f <file>` | Рендер с файлом значений |
| `helm template <name> <chart> --show-only <file>` | Рендер только указанного шаблона |
| `helm template <name> <chart> --debug` | Рендер с выводом значений и шаблонов |
| `helm template <name> <chart> --output-dir <dir>` | Сохранение рендеренных манифестов в файлы |
| `helm lint <chart>` | Локальная валидация чарта |
| `helm lint <chart> --strict` | Строгая валидация (все предупреждения = ошибки) |
| `helm lint <chart> -f <file>` | Линтинг с конкретными значениями |

**Глубокая отладка чарта:**

1. **Валидация синтаксиса:**
    ```bash
    helm lint ./my-chart --strict
    # → 0 chart(s) linted, 0 chart(s) failed
    ```

2. **Локальный рендеринг:**
    ```bash
    helm template my-release ./my-chart -f my-values.yaml > rendered.yaml
    ```

3. **Рендер конкретного шаблона:**
    ```bash
    helm template my-release ./my-chart --show-only templates/deployment.yaml
    ```

4. **Проверка в кластере (Dry-run с SSA):**
    В v4 `--dry-run` выполняет валидацию на стороне сервера (Server-side dry-run), что точнее проверяет права и схемы.
    ```bash
    helm upgrade --install my-app ./my-chart --dry-run --debug
    ```

### 13. Окружение и настройка (helm env / helm completion)

| Команда | Описание |
|---------|----------|
| `helm env` | Вывод переменных окружения Helm |
| `helm completion bash` | Генерация completion-скрипта для Bash |
| `helm completion zsh` | Генерация completion-скрипта для Zsh |
| `helm completion fish` | Генерация completion-скрипта для Fish |

**Переменные окружения:**

| Переменная | Описание |
|------------|----------|
| `HELM_PLUGINS` | Путь к директории с плагинами (по умолчанию `~/.local/share/helm/plugins`). |
| `HELM_CONFIG_HOME` | Директория для конфигурационных файлов. |
| `HELM_CACHE_HOME` | Директория кеша (загруженные чарты, OCI-манифесты). |
| `HELM_DATA_HOME` | Директория для данных (история, ревизии). |
| `HELM_NAMESPACE` | Namespace по умолчанию (если не указан в команде). |
| `HELM_KUBECONTEXT` | Контекст kubectl по умолчанию. |
| `HELM_DEBUG` | Включает детальное логирование для отладки. |
| `HELM_NO_PLUGINS` | Отключает загрузку плагинов (полезно в CI с ограниченными правами). |

**Установка completion:**
```bash
# Bash (Linux)
helm completion bash > /etc/bash_completion.d/helm

# Bash (macOS с Homebrew)
helm completion bash > $(brew --prefix)/etc/bash_completion.d/helm

# Zsh
helm completion zsh > "${fpath[1]}/_helm"

# ФISH
helm completion fish > ~/.config/fish/completions/helm.fish
```

---

## Практические сценарии

### Полный рабочий процесс: Развертывание приложения

1. **Поиск и выбор:**
    ```bash
    helm search hub kube-prometheus-stack
    helm search repo prometheus-community
    ```

2. **Подготовка конфигурации:**
    ```bash
    helm show values prometheus-community/kube-prometheus-stack > values.yaml
    # Редактирование values.yaml под нужды...
    ```

3. **Валидация перед деплоем:**
    ```bash
    helm lint prometheus-community/kube-prometheus-stack -f values.yaml
    helm template monitoring prometheus-community/kube-prometheus-stack -f values.yaml > rendered.yaml
    # Проверка rendered.yaml...
    ```

4. **Развертывание с контролем атомарности:**
    ```bash
    helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
      --namespace monitoring \
      --create-namespace \
      -f values.yaml \
      --atomic \
      --timeout 10m
    ```

5. **Проверка статуса:**
    ```bash
    helm status monitoring -n monitoring
    helm history monitoring -n monitoring
    ```

6. **Тестирование:**
    ```bash
    helm test monitoring -n monitoring --logs
    ```

### Работа сOCI-реестрами (Стандарт v4)

```bash
# 1. Авторизация
helm registry login registry.example.com

# 2. Упаковка и публикация
helm package ./my-chart
helm push my-chart-1.2.3.tgz oci://registry.example.com/charts

# 3. Инспектирование и установка по дигесту (Immutable)
helm show values oci://registry.example.com/charts/my-chart --version 1.2.3
helm upgrade --install my-app oci://registry.example.com/charts/my-app@sha256:7f...
```

### Детальное управление значениями через `--set`

**1. Вложенные переменные:**
```bash
# YAML: mariadb.auth.username: "user0"
helm install my-release ./my-chart --set mariadb.auth.username=user0
```

**2. Списки и массивы:**
```bash
# Эквивалентно YAML: servers: [nginx, apache]
helm install my-release ./my-chart --set servers={nginx,apache}
```

**3. Доступ по индексу:**
```bash
# Установка порта для первого элемента массива
helm install my-release ./my-chart --set servers[0].port=80
```

**4. Экранирование спецсимволов:**
```bash
# Значение с запятой
helm install my-release ./my-chart --set name="value1\,value2"

# Значение с точкой (предотвращает интерпретацию как вложенного ключа)
helm install my-release ./my-chart --set host="host\.example\.com"
```

**5. Многострочные значения:**
```bash
# Значение с переносом строки
helm install my-release ./my-chart --set 'config.json={"key": "value"}'
```

### Предварительный просмотр изменений (helm diff)

Плагин `helm-diff` позволяет увидеть, что именно изменится при upgrade, до его выполнения:

```bash
# Установка плагина
helm plugin install https://github.com/databus23/helm-diff

# Просмотр diff перед upgrade
helm diff upgrade my-release ./my-chart -f values.yaml

# Просмотр diff с конкретной ревизией
helm diff upgrade my-release ./my-chart -f values.yaml --revision 5

# Автоматический update без интерактивного подтверждения
helm diff upgrade my-release ./my-chart -f values.yaml --allow-unreleased
```

**Пример вывода:**
```diff
- ## my-release-my-chart
+ ## my-release-my-chart
  ...
- replicas: 2
+ replicas: 3
- image: nginx:1.25
+ image: nginx:1.27
```

### Проверка изменений перед upgrade

```bash
# 1. Сравнение текущих и новых значений
helm get values my-release -n prod > current-values.yaml
diff current-values.yaml new-values.yaml

# 2. Рендер текущей и новой конфигурации
helm template my-release ./my-chart -f current-values.yaml > current-rendered.yaml
helm template my-release ./my-chart -f new-values.yaml > new-rendered.yaml
diff current-rendered.yaml new-rendered.yaml

# 3. Dry-run в кластере
helm upgrade --install my-release ./my-chart -f new-values.yaml --dry-run --debug
```

### Использование Пост-рендеринга

Если чарт не поддерживает нужный параметр, используйте внешние инструменты для модификации манифестов:

```bash
# Через WASM-плагин (v4 рекомендуется)
helm install my-app ./my-chart --post-renderer ./kustomize-wrapper.sh

# Через Kustomize
helm template my-release ./my-chart | kustomize build . | kubectl apply -f -

# Через yq
helm template my-release ./my-chart | yq '.items[].metadata.labels += {"custom": "label"}' | kubectl apply -f -
```

### Удаление с сохранением истории

```bash
helm uninstall myapp --keep-history
# → Ресурсы удалены, но ревизии сохранены в Secret. Можно выполнить rollback.
helm rollback myapp 3
```

### Multi-namespace развертывание

```bash
# Установка в разные namespace из одного чарта
for ns in dev staging prod; do
  helm upgrade --install my-app ./my-chart \
    --namespace $ns \
    --create-namespace \
    -f values-${ns}.yaml \
    --atomic
done
```

---

## Диагностика и устранение неполадок

### Частые ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Error: release <name> failed, timed-out` | Ресурсы не стали Ready за timeout | Увеличьте `--timeout` или проверьте readiness/probe |
| `Error: INSTALLATION FAILED: failed pre-install` | Хук pre-install завершился с ошибкой | Проверьте логи Job: `kubectl logs <hook-pod>` |
| `Error: cannot re-use a name that is still in use` | Релиз с таким именем уже существует | Используйте `helm upgrade --install` или выберите новое имя |
| `Error: Kubernetes API timed out` | Проблемы с доступом к API-серверу | Проверьте kubeconfig и права доступа |
| `Error: named templates "..." not defined` | Отсутствует функция в `_helpers.tpl` | Проверьте, что все `include` и `define` присутствуют |
| `Warning: ResourcePolicy "..." is not valid` | Неверный синтаксис политики | Проверьте `helm.sh/resource-policy` аннотацию |
| `another operation (install/upgrade/rollback) is in progress` | Предыдущая операция не завершена | Дождитесь завершения или выполните `helm rollback` |
| `Error: chart requires kubeVersion: X.Y.Z` | Версия Kubernetes не соответствует требованиям чарта | Обновите кластер или используйте более старую версию чарта |

### Команды отладки

```bash
# Просмотр логов.failed релиза
helm status my-release --show-desc

# Просмотр всех манифестов, применённых релизом
helm get manifest my-release -n prod

# Просмотр ресурсов, созданных релизом в кластере
kubectl get all -l app.kubernetes.io/instance=my-release -n prod

# Просмотр ошибок в Pod'ах
kubectl get pods -l app.kubernetes.io/instance=my-release -n prod --field-selector=status.phase!=Running

# Проверка конфликтов SSA (v4)
kubectl get deployment my-release -n prod -o yaml | grep -A5 managedFields

# Просмотр всех Secret'ов с релизами
kubectl get secrets -l owner=helm -A
```

### Восстановление из failed-состояния

```bash
# 1. Проверка текущего статуса
helm history my-release -n prod

# 2. Откат к последней работающей ревизии
helm rollback my-release <working-revision> -n prod

# 3. Если откат не помог — принудительное обновление
helm upgrade --install my-release ./my-chart \
  -f values.yaml \
  -n prod \
  --force \
  --cleanup-on-fail

# 4. В крайнем случае — удаление и пересоздание
helm uninstall my-release -n prod --keep-history
helm install my-release ./my-chart -f values.yaml -n prod --atomic
```

---

## Форматы вывода и автоматизация

Для интеграции со скриптами используйте JSON/YAML вывод:

```bash
# Список релизов в JSON
helm list -A -o json | jq '.[].name'

# Статус в YAML
helm status my-release -o yaml

# История в JSON для парсинга
helm history my-release -o json | jq '.[] | select(.status=="failed")'

# Фильтрация.failed релизов во всех namespace
helm list -A --status failed -o json | jq -r '.[].name + " " + .namespace'
```

---

## Интеграция с CI/CD

### GitLab CI

```yaml
stages:
  - lint
  - package
  - deploy

variables:
  CHART_DIR: "./chart"
  HELM_RELEASE: "my-app"
  KUBE_NAMESPACE: "production"

helm:lint:
  stage: lint
  image: alpine/helm:3.22.0
  script:
    - helm lint $CHART_DIR --strict
    - helm template $HELM_RELEASE $CHART_DIR > /dev/null

helm:package:
  stage: package
  image: alpine/helm:3.22.0
  script:
    - helm package $CHART_DIR --version $CI_COMMIT_TAG
  artifacts:
    paths:
      - "*.tgz"

helm:deploy:
  stage: deploy
  image: alpine/helm:3.22.0
  script:
    - helm registry login $OCI_REGISTRY --username $CI_DEPLOY_USER --password-stdin <<< $CI_DEPLOY_PASSWORD
    - helm push *.tgz oci://$OCI_REGISTRY
    - helm upgrade --install $HELM_RELEASE oci://$OCI_REGISTRY/$HELM_RELEASE \
        --version $CI_COMMIT_TAG \
        --namespace $KUBE_NAMESPACE \
        --create-namespace \
        -f values-production.yaml \
        --atomic \
        --timeout 10m
  only:
    - tags
  when: manual
```

### GitHub Actions

```yaml
name: Deploy Helm Chart

on:
  push:
    tags:
      - 'v*'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Helm
        uses: azure/setup-helm@v3

      - name: Helm Lint
        run: helm lint ./chart --strict

      - name: Helm Template (validate)
        run: helm template my-release ./chart > /dev/null

      - name: Helm Package
        run: helm package ./chart

      - name: Helm Push to OCI
        run: |
          echo "${{ secrets.OCI_PASSWORD }}" | helm registry login registry.example.com --username ${{ secrets.OCI_USERNAME }} --password-stdin
          helm push *.tgz oci://registry.example.com/charts

      - name: Helm Deploy
        run: |
          helm upgrade --install my-app oci://registry.example.com/charts/my-app \
            --version ${{ github.ref_name }} \
            --namespace production \
            --create-namespace \
            -f values-production.yaml \
            --atomic \
            --timeout 10m
```

### Makefile (универсальный)

```makefile
CHART_DIR := ./chart
RELEASE := my-app
NAMESPACE := production
OCI_REGISTRY := registry.example.com/charts

.PHONY: lint template install upgrade diff test

lint:
	helm lint $(CHART_DIR) --strict

template:
	helm template $(RELEASE) $(CHART_DIR) -f values-$(ENV).yaml

install:
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
		-f values-$(ENV).yaml \
		--namespace $(NAMESPACE) \
		--create-namespace \
		--atomic

upgrade:
	helm upgrade --install $(RELEASE) $(CHART_DIR) \
		-f values-$(ENV).yaml \
		--namespace $(NAMESPACE) \
		--atomic \
		--dependency-update

diff:
	helm diff upgrade $(RELEASE) $(CHART_DIR) -f values-$(ENV).yaml

test:
	helm test $(RELEASE) -n $(NAMESPACE) --logs

package:
	helm package $(CHART_DIR)

push: package
	helm push *.tgz oci://$(OCI_REGISTRY)
```

---

## Дополнительная информация

### Идемпотентность развертывания через SSA

Команда `helm upgrade --install` (или сокращенно `helm upgrade -i`) является "золотым стандартом" для CI/CD. В Helm v4 она по умолчанию использует **Server-Side Apply (SSA)**. Это гарантирует, что Helm корректно сосуществует с другими контроллерами (например, HPA), которые могут изменять поля ресурсов. Слияние происходит в Kubernetes, что исключает "затирание" внешних изменений.

### Автоматическая генерация имени релиза

Флаг `--generate-name` автоматически создаёт уникальное имя релиза в формате `<chart-name>-<random-suffix>`. Это удобно для динамических окружений или тестирования:

```bash
helm install bitnami/mysql --generate-name
# → mysql-1717894532 (уникальное имя)
```

> **Ограничение:** Для последующих обновлений необходимо использовать уже сгенерированное имя через `helm upgrade <имя>`.

### Управление значениями релиза

Значения, установленные через `--set` или переданные в файлах, сохраняются в Secret релиза (в виде снапшота для SSA) и доступны для просмотра:

```bash
# Просмотр пользовательских значений текущей ревизии
helm get values my-release -n prod

# Просмотр всех значений (включая defaults из values.yaml чарта)
helm get values my-release -n prod --all
```

**Сброс кастомных значений:**
```bash
# Удаляет все --set значения и возвращает значения из values.yaml чарта
helm upgrade my-release ./my-chart --reset-values -n prod
```

**Переиспользование текущих значений:**
```bash
# При обновлении переиспользует текущие значения, overlay с новыми
helm upgrade my-release ./my-chart --reuse-values --set replicas=3
```

---

## См. также

- [Обзор Helm](./helm_overview.md) — архитектура v4 и SSA.
- [Управление версиями релизов](./helm_release_versioning.md) — SemVer и ревизии.
- [Хуки и тестирование в Helm](./helm_hooks_and_tests.md) — сложные сценарии жизненного цикла.
- [Плагины Helm](./helm_plugins.md) — `helm-diff` и WASM-расширения.
- [Практические сценарии Helm-чартов](./helm_chart_practical_scenarios.md) — Umbrella и Shared чарты.
- [Зависимости и Library Charts](./helm_dependencies_and_library_charts.md) — композиция и переиспользование чартов.
- [Паттерны и устранение неисправностей](./Advanced/patterns_troubleshooting.md) — паттерны проектирования и диагностика.
- [Продвинутые сценарии Helm](./Advanced/scenarios.md) — OCI, Sigstore, пост-рендеринг, адаптивные чарты.
