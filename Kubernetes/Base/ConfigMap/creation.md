# Создание ConfigMap

## Определения

**ConfigMap** — объект API Kubernetes, предназначенный для хранения неконфиденциальных конфигурационных данных в виде пар «ключ-значение». Он позволяет отделить конфигурацию от кода приложения, обеспечивая переносимость образов контейнеров между различными окружениями и соблюдение принципа **Separation of Concerns**.

## Основные концепции

Управление жизненным циклом ConfigMap осуществляется тремя основными способами:

1.  **Декларативный (GitOps-путь):** Описание состояния через YAML-манифесты. Обеспечивает версионирование, аудит и Code Review конфигураций.
2.  **Генеративный (Automation-путь):** Использование инструментов (Kustomize, Helm) для динамического создания объектов из внешних источников (файлов, переменных окружения). В Kustomize этот метод считается стандартом (Name Hashing), так как он автоматически инициирует обновление подов при изменении данных.
3.  **Императивный (Debug-путь):** Создание через команды `kubectl create`. Применяется для быстрого прототипирования, отладки или генерации начальных YAML-шаблонов.

### Важные ограничения

*   **Namespace Scope:** ConfigMap является ресурсом уровня пространства имен. Поды могут использовать только те ConfigMap, которые находятся в том же Namespace.
*   **Лимит размера:** Максимальный размер одного объекта ограничен **1 MiB** (ограничение хранилища etcd).
*   **Кодировка:** Поле `data` поддерживает только строки в кодировке **UTF-8**. Для бинарных данных используется `binaryData`.

## Практические сценарии

### Декларативный подход: YAML-манифест

Стандарт для Production-окружений. Позволяет описывать как простые ключи, так и целые файлы конфигурации.

```yaml
# app-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: prod
  labels:
    app: backend
    tier: middle
data:
  # Простые пары ключ-значение
  DB_PORT: "5432"
  LOG_LEVEL: "INFO"

  # Содержимое файла конфигурации (многострочный блок)
  server.conf: |
    server {
        timeout: 30s
        max_connections: 100
    }
```

**Применение:**
```bash
kubectl apply -f app-config.yaml
# → configmap/app-config created
```

---

### Генеративный подход: Kustomize (configMapGenerator)

Kustomize (встроен в `kubectl -k`) автоматизирует создание ConfigMap и управление их версиями через **Name Hashing**. При изменении содержимого файлов Kustomize генерирует новое имя (например, `app-config-f7h8z9`), что вынуждает Kubernetes выполнить Rolling Update для всех зависимых Deployments.

```yaml
# kustomization.yaml
configMapGenerator:
- name: app-config
  # Создание из файлов (имя файла станет ключом)
  files:
    - configs/nginx.conf
    - configs/app.properties
  # Создание из литералов
  literals:
    - API_ENDPOINT=https://api.internal.local
  # Создание из .env файла
  envs:
    - .env.prod

generatorOptions:
  # Установка флага неизменяемости (Best Practice)
  immutable: true
  labels:
    managed-by: kustomize
```

---

### Императивный подход: kubectl create

Используется для быстрой генерации объектов «на лету» или создания шаблонов.

**Создание из различных источников:**
```bash
# Из литералов (явные пары ключ=значение)
kubectl create configmap my-lite --from-literal=DEBUG=true --from-literal=COLOR=red

# Из конкретного файла (имя файла станет ключом)
kubectl create configmap my-file --from-file=config.yaml

# С явным указанием ключа для файла
kubectl create configmap my-key --from-file=custom_key=path/to/real_file.txt

# Из директории (все файлы в директории станут ключами)
kubectl create configmap my-dir --from-file=./configs/

# Из .env файла
kubectl create configmap my-env --from-env-file=.env
```

**Генерация манифеста (Dry-run):**
```bash
# Получение YAML-шаблона без создания объекта в кластере
kubectl create configmap app-template --from-literal=key=value --dry-run=client -o yaml > cm.yaml
```

---

### Работа с бинарными данными (binaryData)

Для хранения файлов, не являющихся текстом в UTF-8 (сертификаты, изображения, скомпилированные артефакты), используется поле `binaryData`. Данные должны быть закодированы в **Base64**.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: binary-assets
binaryData:
  logo.png: "iVBORw0KGgoAAAANSUh..."
```

*Примечание: При использовании `kubectl create configmap --from-file` для бинарных файлов, инструмент автоматически помещает их в `binaryData`.*

---

### Неизменяемые (Immutable) ConfigMap

Начиная с Kubernetes v1.21, для оптимизации производительности рекомендуется использовать флаг `immutable: true`.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: static-settings
immutable: true
data:
  VERSION: "1.2.0"
```

**Преимущества:**
*   **Снижение нагрузки на API-сервер:** Kubelet перестает отслеживать изменения (Watch) этого ресурса.
*   **Безопасность:** Защита от случайных ручных правок (`kubectl edit`).
*   **Предсказуемость:** Обновление конфигурации гарантированно требует создания нового объекта и перезапуска подов.

## Дополнительная информация

### Валидация и проверка

Перед применением изменений рекомендуется выполнить следующие проверки:

1.  **Предварительный просмотр изменений:**
    ```bash
    kubectl diff -f cm.yaml
    ```
2.  **Валидация на стороне сервера (Server-side dry-run):**
    Проверяет манифест через **[Admission Controllers](../../Concepts/admission_controllers.md)** (например, лимиты Quota или политики безопасности) без записи в etcd.
    ```bash
    kubectl apply -f cm.yaml --dry-run=server
    ```
3.  **Проверка структуры данных:**
    ```bash
    kubectl get configmap <name> -o yaml
    # Проверка конкретного ключа
    kubectl get cm <name> -o jsonpath='{.data.DB_PORT}'
    ```

### Сравнение методов создания

| Метод | Уровень контроля | Авто-обновление подов | Сфера применения |
| :--- | :--- | :--- | :--- |
| **YAML (Declarative)** | Высокий | Нет (ручной рестарт) | Базовые настройки, GitOps |
| **Kustomize** | Средний | **Да** (Name Hashing) | Production, CI/CD пайплайны |
| **Helm** | Высокий | Да (через аннотации с хешем) | Сложные чарты с логикой |
| **kubectl (Imperative)** | Низкий | Нет | Отладка, генерация шаблонов |

### Рекомендации (2024-2026)

*   **Предпочитайте неизменяемость:** Используйте `immutable: true` для всех стабильных конфигураций.
*   **Используйте Name Hashing:** Это единственный надежный способ гарантировать, что все реплики приложения используют актуальную версию конфига.
*   **Контролируйте размер:** Если размер конфигурации приближается к 1 MiB, разделите её на несколько ConfigMap или используйте тома (PVC).
*   **Разделяйте данные:** Не смешивайте настройки разных приложений в одном ConfigMap. Один сервис — один (или несколько) ConfigMap.
*   **Не храните секреты:** Для паролей, ключей и токенов всегда используйте [Secret](../secrets/secrets_basics.md).

**См. также:**

* [Лучшие практики ConfigMap](./best_practices.md) — нейминг, структура и организация.
* [Использование ConfigMap в подах](./pod_usage.md) — монтирование и переменные окружения.
* [Неизменяемые ConfigMap](./immutable.md) — глубокое погружение в оптимизацию.
* [Обновление и Rollout](./update_and_rollout.md) — стратегии актуализации настроек без простоя.
