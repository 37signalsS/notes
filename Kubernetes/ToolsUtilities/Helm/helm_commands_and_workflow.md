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

---

## Базовые концепции

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
При обновлении релиза можно откатить значения к дефолтным:
```bash
# Удаляет все --set значения и возвращает значения из values.yaml чарта
helm upgrade my-release ./my-chart --reset-values -n prod
```

### Атомарность, ожидание и управление состоянием

Helm v4 предоставляет расширенный контроль над процессом деплоя, интегрируя библиотеку `kstatus` для определения готовности.

| Флаг | Описание | Доступен для |
|------|----------|-------------|
| `--timeout <duration>` | Время ожидания готовности (по умолчанию 5m). | `install`, `upgrade`, `rollback` |
| `--wait` | Ждёт готовности всех подов, PVC, Service (LoadBalancer IP) и CRD (через kstatus). | `install`, `upgrade`, `rollback` |
| `--atomic` | Включает `--wait` + автоматический `rollback` при сбое или таймауте. | `install`, `upgrade` |
| `--cleanup-on-fail` | Удаляет созданные ресурсы, если транзакция не удалась (предотвращает конфликты). | `install`, `upgrade` |
| `--server-side` | Явное включение SSA (в v4 активно по умолчанию). | `install`, `upgrade` |
| `--force-conflicts` | Перехват владения полями (field ownership) у других контроллеров. | `install`, `upgrade` |

### Порядок создания ресурсов (Kind Order)

Helm создаёт ресурсы в строгой последовательности, чтобы обеспечить удовлетворение зависимостей внутри кластера (например, создание CRD до самих ресурсов):

1.  **Namespace**
2.  **NetworkPolicy**, **ResourceQuota**, **LimitRange**
3.  **ServiceAccount**, **Secret**, **ConfigMap**
4.  **PersistentVolume**, **PersistentVolumeClaim**
5.  **CustomResourceDefinition** (приоритетно из директории `crds/`)
6.  **ClusterRole**, **Role** (и их Binding)
7.  **Deployment**, **StatefulSet**, **DaemonSet**, **Job**
8.  **Service**, **Ingress**
9.  **APIService**

---

## Практические сценарии

### Глубокая отладка чарта

1.  **Валидация синтаксиса:**
    ```bash
    helm lint ./my-chart
    # → 0 chart(s) linted, 0 chart(s) failed
    ```

2.  **Локальный рендеринг:**
    Выводит итоговые манифесты в stdout без взаимодействия с Kubernetes.
    ```bash
    helm template my-release ./my-chart -f my-values.yaml > rendered.yaml
    ```

3.  **Проверка в кластере (Dry-run с SSA):**
    В v4 `--dry-run` выполняет валидацию на стороне сервера (Server-side dry-run), что точнее проверяет права и схемы.
    ```bash
    helm upgrade --install my-app ./my-chart --dry-run --debug
    ```

### Работа с OCI-реестрами (Стандарт v4)

```bash
# 1. Авторизация (требуется только домен)
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
Используйте `\` для запятых и точек в значениях:
```bash
# Значение с запятой
helm install my-release ./my-chart --set name="value1\,value2"

# Значение с точкой (предотвращает интерпретацию как вложенного ключа)
helm install my-release ./my-chart --set host="host\.example\.com"
```

### Пример рабочего процесса: Развертывание приложения

1.  **Поиск и выбор:**
    ```bash
    helm search hub kube-prometheus-stack
    helm search repo prometheus-community
    ```

2.  **Подготовка конфигурации:**
    ```bash
    helm show values prometheus-community/kube-prometheus-stack > values.yaml
    ```

3.  **Развертывание с контролем атомарности:**
    ```bash
    helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
      --namespace monitoring \
      --create-namespace \
      -f values.yaml \
      --atomic \
      --timeout 10m
    ```

4.  **Управление историей:**
    ```bash
    helm list -A
    helm history monitoring -n monitoring
    helm rollback monitoring 1 -n monitoring
    ```

---

## Дополнительная информация

### Инспектирование и интроспекция

-   `helm show chart <chart>` — просмотр метаданных (`Chart.yaml`).
-   `helm show values <chart>` — просмотр параметров по умолчанию.
-   `helm get all <release>` — извлечение всех данных релиза из кластера (манифесты + values).
-   `helm get notes <release>` — просмотр инструкций из `NOTES.txt`.

### Форматы вывода и автоматизация

Для интеграции со скриптами используйте JSON/YAML вывод:
```bash
helm list -A -o json | jq '.[].name'
helm status my-release -o yaml
```

### Удаление с сохранением истории

```bash
helm uninstall myapp --keep-history
# → Ресурсы удалены, но ревизии сохранены в Secret. Можно выполнить rollback.
```

### Использование Пост-рендеринга

Если чарт не поддерживает нужный параметр, используйте внешние инструменты (например, Kustomize) для модификации манифестов "на лету":
```bash
helm install my-app ./my-chart --post-renderer ./kustomize-wrapper.sh
```

---

## См. также

*   [Обзор Helm](./helm_overview.md) — архитектура v4 и SSA.
*   [Управление версиями релизов](./helm_release_versioning.md) — SemVer и ревизии.
*   [Хуки и тестирование в Helm](./helm_hooks_and_tests.md) — сложные сценарии жизненного цикла.
*   [Плагины Helm](./helm_plugins.md) — `helm-diff` и WASM-расширения.
*   [Практические сценарии Helm-чартов](./helm_chart_practical_scenarios.md) — Umbrella и Shared чарты.
