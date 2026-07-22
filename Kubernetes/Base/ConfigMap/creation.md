# Создание ConfigMap

## Определения

**ConfigMap** — объект API (Application Programming Interface) Kubernetes для хранения неконфиденциальных конфигурационных данных в виде пар «ключ-значение». Он позволяет отделить конфигурацию от кода приложения, обеспечивая переносимость образов между окружениями и соблюдение принципа **Separation of Concerns**.

## Основные концепции

Существует три основных подхода к управлению жизненным циклом ConfigMap:

1. **Декларативный** (стандарт отрасли) — описание через YAML-манифесты. Позволяет использовать Code Review, версионирование (GitOps) и аудит изменений.
2. **Генеративный** (Kustomize / Helm) — автоматическое создание ConfigMap из внешних файлов или литералов. В Kustomize этот подход является предпочтительным, так как позволяет автоматически обновлять поды при изменении конфигурации за счет хеширования имен.
3. **Императивный** — через команды `kubectl`. Используется преимущественно для отладки, прототипирования или генерации базовых YAML-шаблонов.

## Практические сценарии

### Декларативно: из YAML-манифеста

Этот способ используется для Production-сред. Манифест может содержать как простые значения, так и целые блоки конфигурационных файлов.

```yaml
# app-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: my-app
  labels:
    app: backend
    env: prod
data:
  # Простые пары ключ-значение
  APP_COLOR: "blue"
  LOG_LEVEL: "info"

  # Содержимое файла конфигурации
  nginx.conf: |
    server {
        listen 80;
        location / {
            root /app;
            index index.html;
        }
    }
```

**Применение:**
```bash
kubectl apply -f app-config.yaml
# → configmap/app-config created
```

---

### Генеративный подход: Kustomize (configMapGenerator)

Kustomize (встроен в `kubectl -k`) позволяет генерировать ConfigMap из файлов свойств или `.env`. Основное преимущество — **Name Hashing**: Kustomize добавляет хеш содержимого к имени (например, `app-config-f7h8z9`). При изменении данных имя меняется, что гарантирует перезапуск подов в Deployment.

```yaml
# kustomization.yaml
configMapGenerator:
- name: app-config
  files:
    - configs/server.conf
  literals:
    - API_URL=https://api.example.com
generatorOptions:
  # Установка флага неизменяемости (Best Practice 2024+)
  immutable: true
  labels:
    team: devops
```

---

### Императивно: генерация и создание через kubectl

Для создания объектов «на лету» или генерации заготовок манифестов.

**Создание из литералов и файлов:**
```bash
kubectl create configmap my-config \
  --from-literal=DEBUG=true \
  --from-file=config.json
```

**Совет: Генерация манифеста (Dry-run):**
Вместо написания YAML вручную, используйте `dry-run` для получения чистого шаблона:
```bash
kubectl create configmap app-v1-config --from-env-file=.env --dry-run=client -o yaml > cm.yaml
```

**Валидация перед применением (Server-side dry-run):**
Проверка манифеста на соответствие политикам кластера (Admission Controllers) без фактического создания:
```bash
kubectl apply -f cm.yaml --dry-run=server
```

---

### Работа с бинарными данными (binaryData)

Для хранения не-UTF8 данных (сертификаты, изображения, скомпилированные конфиги) используется поле `binaryData`. Данные должны быть закодированы в **Base64**.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cert-config
binaryData:
  server.crt: "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0t..."
```

При использовании `kubectl create configmap --from-file=...` инструмент автоматически определяет бинарный формат и помещает данные в соответствующее поле.

---

### Неизменяемые (Immutable) ConfigMap

Для высоконагруженных систем рекомендуется устанавливать флаг `immutable: true`. Это отключает механизм `watch` со стороны `kubelet`, снижая нагрузку на **API Server**.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: static-config
immutable: true
data:
  config.yaml: |
    key: value
```
*Примечание: для изменения таких конфигов требуется создание нового объекта с новым именем.* Подробнее см. [Неизменяемые ConfigMap](./immutable.md).

## Дополнительная информация

### Проверка созданного ConfigMap

```bash
# Список всех ConfigMap в текущем пространстве имен
kubectl get configmaps

# Просмотр структуры и данных в формате YAML
kubectl get configmap app-config -o yaml

# Получение детальной информации (включая метаданные и события)
kubectl describe configmap app-config

# Извлечение конкретного значения через jsonpath
kubectl get configmap app-config -o jsonpath='{.data.APP_COLOR}'
# → blue
```

### Сравнение методов создания

| Метод | Плюсы | Минусы | Когда использовать |
| :--- | :--- | :--- | :--- |
| **YAML Манифест** | Полный контроль, читаемость | Ручное обновление подов | GitOps, простые приложения |
| **Kustomize** | Авто-рестарт подов, IaC | Требует настройки kustomize | Production, сложные окружения |
| **kubectl create** | Скорость | Нет истории, сложность поддержки | Отладка, генерация шаблонов |

### Рекомендации по созданию (2024-2026)

* **Используйте хеширование имен:** это единственный надежный способ гарантировать, что все поды перечитают конфиг при обновлении.
* **Соблюдайте лимит 1 MiB:** ConfigMap хранится в etcd. Для больших файлов (>500KB) рассмотрите возможность монтирования через `PersistentVolume`.
* **Избегайте хранения секретов:** никогда не храните пароли или ключи в ConfigMap, даже в `binaryData`. Используйте [Secret](../secrets/secrets_basics.md).
* **Проверяйте изменения:** всегда используйте `kubectl diff` перед применением новых конфигураций.

**См. также:**

* [Лучшие практики ConfigMap](./best_practices.md) — нейминг, версионирование и структура.
* [Использование ConfigMap в подах](./pod_usage.md) — монтирование и переменные окружения.
* [Неизменяемые ConfigMap](./immutable.md) — оптимизация и безопасность.
* [Обновление и Rollout](./update_and_rollout.md) — стратегии актуализации настроек.
