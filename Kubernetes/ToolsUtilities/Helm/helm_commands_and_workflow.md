# Основные команды и рабочий процесс Helm

Полный жизненный цикл управления Helm-приложениями: от поиска чарта до установки, отладки, управления релизами в кластере и работы с OCI-реестрами.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Релиз (Release)** | Развёрнутый экземпляр чарта в Kubernetes-кластере. См. [Управление версиями релизов](./helm_release_versioning.md) |
| **Ревизия (Revision)** | Порядковый номер версии релиза, увеличивающийся при каждом `upgrade` или `rollback`. |
| **Идемпотентность** | Свойство операции давать одинаковый результат при повторных вызовах (реализовано через `upgrade --install`). |
| **helm upgrade --install** | Универсальная команда: устанавливает новый релиз или обновляет существующий. |
| **helm template** | Локальный рендер шаблонов без обращения к кластеру. Ключевой инструмент отладки. |
| **helm lint** | Валидация чарта на синтаксические ошибки и соответствие лучшим практикам. |
| **helm rollback** | Откат релиза к одной из предыдущих ревизий. |
| **OCI (Open Container Initiative)** | Стандарт хранения Helm-чартов в контейнерных реестрах (Registry) как артефактов. |

---

## Базовые концепции

### Идемпотентность развертывания

Команда `helm upgrade --install` (или сокращенно `helm upgrade -i`) является "золотым стандартом" для CI/CD. Она устанавливает релиз, если он не существует, или обновляет существующий. Это обеспечивает предсказуемый результат при многократных вызовах и предотвращает ошибки в пайплайнах.

### Автоматическая генерация имени релиза

Флаг `--generate-name` автоматически создаёт уникальное имя релиза в формате `<chart-name>-<random-suffix>`. Удобно для тестовых развёртываний, когда имя не имеет значения:

```bash
helm install bitnami/mysql --generate-name
# → mysql-1717894532 (уникальное имя с рандомным суффиксом)
```

> **Ограничение:** `helm install --generate-name` только устанавливает релиз. Для последующих обновлений нужно знать сгенерированное имя и использовать `helm upgrade <имя>`.

### Управление значениями релиза

Значения, установленные через `--set` или переданные в файлах, сохраняются в Secret релиза и доступны для просмотра:

```bash
# Просмотр пользовательских значений текущей ревизии
helm get values my-release -n prod

# Просмотр всех значений (включая defaults из values.yaml чарта)
helm get values my-release -n prod --all
```

**Сброс кастомных значений:**

При обновлении релиза можно откатить значения, ранее установленные через `--set`, к значениям по умолчанию из чарта:

```bash
# Сброс всех --set значений к дефолтным из values.yaml чарта
helm upgrade my-release ./my-chart --reset-values -n prod
```

Флаг `--reset-values` удаляет все кастомные значения, сохранённые в Secret релиза, и использует только значения из текущего `values.yaml` (или файла, указанного через `-f`).

### Атомарность, ожидание и таймауты

Helm 3 предоставляет мощные инструменты для контроля успешности развертывания. Флаг `--atomic` включает `--wait` и добавляет автоматический откат при достижении таймаута или сбое проверки готовности.

| Флаг | Описание | Доступен для |
|------|----------|-------------|
| `--timeout <duration>` | Время ожидания готовности ресурсов. По умолчанию 5 минут. Рекомендуется увеличивать для чартов с долгой инициализацией. | `install`, `upgrade`, `rollback` |
| `--wait` | Ждёт, пока все поды в `Ready`, PVC связаны, Deployment получил реплики, а Service (LoadBalancer) получил IP. | `install`, `upgrade`, `rollback` |
| `--wait-for-jobs` | Вместе с `--wait` — ждёт завершения всех Helm Jobs перед тем как считать релиз готовым. | `install`, `upgrade` |
| `--atomic` | Включает `--wait` + автоматический откат к предыдущей ревизии при достижении таймаута или сбое. | `install`, `upgrade` |
| `--cleanup-on-fail` | Удаляет созданные ресурсы, если транзакция не удалась (предотвращает конфликты при повторной попытке). | `install`, `upgrade` |
| `--no-hooks` | Пропускает выполнение Helm Hooks (пре- и пост-инсталляционных скриптов). | `install`, `upgrade`, `rollback`, `uninstall` |
| `--recreate-pods` | **Устарел.** Для Deployment используйте стратегию `Recreate` в манифесте. | `upgrade`, `rollback` |

> **Рекомендация:** Флаг `--atomic` полностью покрывает функциональность `--wait` и предпочтительнее для production, так как автоматически восстанавливает работоспособность системы при сбое.

### Порядок создания ресурсов (Kind Order)

Helm создаёт ресурсы Kubernetes в строгой последовательности для минимизации конфликтов зависимостей:

1. **Namespace**
2. **NetworkPolicy**
3. **ResourceQuota**, **LimitRange**
4. **PodSecurityPolicy** / **PodDisruptionBudget**
5. **ServiceAccount**
6. **Secret**
7. **PersistentVolume** / **PersistentVolumeClaim**
8. **ConfigMap**
9. **CustomResourceDefinition** (только из директории `crds/`)
10. **ClusterRole**, **Role** (и их Binding)
11. **Deployment**, **DaemonSet**, **StatefulSet**, **ReplicaSet**, **Job**
12. **Service**
13. **Ingress**
14. **APIService**

> **Примечание:** Если требуется более тонкое управление порядком (например, ожидание миграции БД перед деплоем приложения), используйте [Helm Hooks](./helm_hooks_and_tests.md).

### Источники для установки чарта

```bash
# Из репозитория (добавленного через helm repo add)
helm install my-release bitnami/wordpress

# Из OCI-реестра (Registry как OCI-артефакт)
helm install my-release oci://registry.example.com/charts/wordpress --version 15.3.0

# Из локального архива .tgz
helm install my-release ./wordpress-15.3.0.tgz

# Из распакованной директории чарта (предпочтительно для разработки)
helm install my-release ./wordpress/

# По прямому URL архива чарта
helm install my-release https://example.com/charts/wordpress-15.3.0.tgz
```

---

## Практические сценарии

### Глубокая отладка чарта

1. **Валидация синтаксиса:**
   ```bash
   helm lint ./my-chart
   ```

2. **Локальный рендеринг (без кластера):**
   Ключевой инструмент разработчика. Рендерит шаблоны локально и выводит итоговые YAML-манифесты в консоль.
   ```bash
   helm template my-release ./my-chart -f my-values.yaml > rendered.yaml
   ```

3. **Проверка в кластере (Dry-run):**
   Отправляет манифесты на API-сервер для проверки схемы и прав, но не сохраняет их.
   ```bash
   helm upgrade --install my-app ./my-chart --dry-run --debug
   ```

### Работа с OCI-реестрами

```bash
# 1. Авторизация
helm registry login registry.example.com -u user

# 2. Упаковка
helm package ./my-chart

# 3. Публикация
helm push my-chart-1.2.3.tgz oci://registry.example.com/charts

# 4. Инспектирование и установка
helm show values oci://registry.example.com/charts/my-chart --version 1.2.3
helm upgrade --install my-app oci://registry.example.com/charts/my-chart --version 1.2.3
```

### Детальное управление значениями через `--set`

**1. Базовый синтаксис:**
```bash
helm install my-release ./my-chart --set replicaCount=5 --set image.tag="1.26.0"
```

**2. Вложенные переменные:**
```bash
# Эквивалентно YAML:
# mariadb:
#   auth:
#     database: "user0db"
#     username: "user0"
helm install my-release ./my-chart \
  --set mariadb.auth.database=user0db \
  --set mariadb.auth.username=user0
```

**3. Списки (массивы):**
```bash
# Эквивалентно YAML:
# servers: [nginx, apache, haproxy]
helm install my-release ./my-chart --set servers={nginx,apache,haproxy}
```

**4. Доступ по индексу:**
```bash
# Установка порта для первого элемента и хоста для второго
helm install my-release ./my-chart \
  --set servers[0].port=80,servers[1].host=secure.example.com
```

**5. Пустые значения и пустые массивы:**
```bash
helm install my-release ./my-chart --set key=null   # Пустое значение (null)
helm install my-release ./my-chart --set list=[]   # Пустой массив
helm install my-release ./my-chart --set list[0]=  # Массив с пустым элементом
```

**6. Экранирование специальных символов:**
Используйте обратный слеш `\` для корректной интерпретации запятых и точек:
```bash
# Значение с запятой (предотвращает разрыв флага)
helm install my-release ./my-chart --set name="value1\,value2"

# Значение с точкой (предотвращает интерпретацию как вложенного ключа)
helm install my-release ./my-chart --set host="host\.example\.com"
```

### Рабочий процесс: пример с kube-ops-view

1. **Управление репозиториями**:
   - Добавление: `helm repo add stable https://charts.helm.sh/stable`
   - Обновление: `helm repo update`

2. **Поиск чарта**:
   - В Artifact Hub: `helm search hub kube-ops-view`
   - В локальных репозиториях: `helm search repo kube-ops-view`

3. **Установка и кастомизация**:
   - Просмотр настроек: `helm show values stable/kube-ops-view`
   - Сохранение values: `helm show values stable/kube-ops-view > values.yaml`
   - Деплой: `helm upgrade --install ops-view stable/kube-ops-view --namespace kube-system -f values.yaml --create-namespace --atomic`

4. **Управление релизом**:
   - Просмотр списка: `helm list -n kube-system`
   - Статус: `helm status ops-view -n kube-system`
   - Откат: `helm rollback ops-view 1`
   - Удаление: `helm uninstall ops-view -n kube-system`

---

## Дополнительная информация

### Инспектирование чартов — `helm show`

Команда позволяет просмотреть содержимое чарта без его установки:
- `helm show chart bitnami/mysql` — метаданные (Chart.yaml).
- `helm show values bitnami/mysql` — содержимое values.yaml.
- `helm show all bitnami/mysql` — всё содержимое (Chart + Values + README).

### Инспектирование работающих релизов — `helm get`

```bash
helm get all my-release -n prod      # Всё: манифесты, values, заметки
helm get values my-release -n prod   # Только пользовательские значения
helm get manifest my-release -n prod # Только итоговый YAML из кластера
helm get notes my-release -n prod    # Только текст NOTES.txt
```

### Форматы вывода (JSON/YAML)

Для автоматизации используйте флаг `-o`:
```bash
helm list -A -o json | jq '.[].name'
helm status my-release -o yaml
```

### Удаление с сохранением истории

```bash
helm uninstall myapp --keep-history
# → Ресурсы удалены, но релиз виден в 'helm list -a' со статусом 'uninstalled'.
# Это позволяет восстановить его позже через 'helm rollback'.
```

### Поиск чартов

**Artifact Hub** ([artifacthub.io](https://artifacthub.io)) — центральная площадка. Рекомендуется использовать веб-интерфейс для оценки популярности и качества документации.

---

## См. также

* [Обзор Helm](./helm_overview.md) — архитектура и основы.
* [Управление версиями релизов](./helm_release_versioning.md) — SemVer, ревизии и жизненный цикл.
* [Хуки и тестирование в Helm](./helm_hooks_and_tests.md) — сложные сценарии развертывания.
* [Плагины Helm](./helm_plugins.md) — `helm-diff`, `helm-secrets`.
* [Практические сценарии Helm-чартов](./helm_chart_practical_scenarios.md) — продвинутые кейсы.
