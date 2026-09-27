# Управление версиями Helm

Helm управляет версиями на трёх уровнях: версия чарта, версия приложения и ревизия релиза в кластере. В актуальной версии **v4 (стандарт 2026 года)** система опирается на стандарт SemVer 2.0.0 для пакетов и механизм **Server-Side Apply (SSA)** для управления состоянием релизов.

---

## Определения

| Сущность | Где определяется | Формат | Назначение |
|----------|------------------|--------|------------|
| **Версия чарта (`version`)** | `Chart.yaml: version` | SemVer 2.0.0 | Идентификация пакета; выбор версии при установке из репозитория или OCI. |
| **Версия приложения (`appVersion`)** | `Chart.yaml: appVersion` | Свободный (обычно SemVer) | Маркер версии ПО внутри контейнера; чисто информационное поле. |
| **Ревизия релиза (`revision`)** | Secret в кластере | Целое число (1, 2, 3…) | Снимок состояния (манифесты + values) для конкретного развёртывания. |
| **apiVersion** | `Chart.yaml: apiVersion` | `v2` (стандарт) | Версия формата чарта. `v2` используется в Helm 3 и 4. |

**Хранилище истории:**

- **Helm 3/4:** Secrets с именем `sh.helm.release.v1.<release-name>.v<revision>` в том же namespace, где находится релиз.
- **Helm 2 (Legacy):** ConfigMaps в namespace `kube-system`. Использование не рекомендуется.

---

## Основные концепции

### Жизненный цикл релиза и статусы

Каждый релиз проходит через предсказуемые статусы. Понимание переходов между ними критично для диагностики и автоматизации.

**Полная схема статусов:**

```
                    helm install
                         │
                         ▼
                   ┌──────────┐
                   │deployed  │ ◄─────── helm upgrade (успешно)
                   └──────────┘         │
                         │              │ (ошибка)
                         │              ▼
                   helm uninstall    ┌────────┐
                         │          │ failed │
                         ▼          └────────┘
                   ┌──────────┐         │
                   │superseded│ ◄─── helm rollback (успешно)
                   └──────────┘         │
                                        │ (ошибка при откате)
                                        ▼
                                  ┌──────────┐
                                  │superseded│ (предыдущая версия становится superseded)
                                  └──────────┘

    промежуточные статусы:
    pending-install → deployed / failed
    pending-upgrade → deployed / failed
    pending-rollback → deployed / failed
```

| Статус | Описание | Как возникает | Что делать |
|--------|----------|---------------|------------|
| `deployed` | Текущая активная версия. Ресурсы управления в кластере принадлежат этой ревизии. | Успешный `install` или `upgrade`. | Работает нормально. |
| `superseded` | Предыдущая версия, замещённая более новой. | При каждом успешном `upgrade` или `rollback` предыдущая ревизия становится superseded. | Нормальное поведение; хранится для истории. |
| `failed` | Ошибка при деплое, обновлении или откате. | Ошибка в шаблонах, нехватка ресурсов, timeout, ошибка хука. | Диагностика: `helm history`, `kubectl describe`, проверка Event'ов. |
| `pending-install` | Ресурсы создаются, но процесс не завершён. | `install` начался, но ещё не завершился (ожидание readiness, хук). | Подождите завершения; если завис — проверьте Pod'ы хуков. |
| `pending-upgrade` | Обновление в процессе. | `upgrade` начался, но не завершился. | Подождите завершения; если завис — `helm rollback`. |
| `pending-rollback` | Откат в процессе. | `rollback` начался, но не завершился. | Подождите завершения; в крайнем случае — ручная очистка Secret'а. |

**Важно для SRE:** Статус `pending-*` блокирует все последующие операции над релизом. Ошибка `another operation (install/upgrade/rollback) in progress` означает, что предыдущая операция не завершилась. Решение — либо дождаться завершения, либо откатить к предыдущей ревизии через `helm rollback`.

### Семантическое версионирование (SemVer)

Версии чартов **обязаны** следовать формату `MAJOR.MINOR.PATCH`:

- **MAJOR** — обратно несовместимые изменения (удаление параметров в `values.yaml`, изменение структуры ресурсов или миграция API-версий K8s).
- **MINOR** — новая функциональность (новые параметры, добавление ресурсов), обратно совместимая.
- **PATCH** — исправления ошибок в шаблонах или документации.

**Пре-релизы и метаданные:**
Helm поддерживает расширенный формат SemVer:
- `1.2.3-alpha.1` — пре-релиз (скрыт в `helm search` без флага `--devel`).
- `1.2.3+build.001` — метаданные сборки (игнорируются при сравнении версий).

**Сравнение версий в шаблонах:**
Для программной проверки версий внутри чарта используется функция `semverCompare`:
```yaml
{{ if semverCompare ">=1.23-0" .Capabilities.KubeVersion.Version }}
# Специфичный для новых версий K8s манифест
{{ end }}
```

> **Важно:** Всегда используйте суффикс `-0` в строках сравнения (например, `>=1.22-0`). Это гарантирует, что версии с метаданными (например, `1.22.0-gke.100` или пре-релизы `1.23.0-alpha`) будут обработаны корректно согласно спецификации SemVer.

**Диапазоны версий в зависимостях (`Chart.yaml`):**

```yaml
dependencies:
  - name: redis
    version: "^17.1.0"    # >=17.1.0 и <18.0.0 (совместимые изменения)
  - name: postgresql
    version: "~12.1.0"    # >=12.1.0 и <12.2.0 (только патчи)
  - name: mysql
    version: ">=8.0.0"    # Любая версия от 8.0.0 и выше
```

### Взаимосвязь `version` и `appVersion`

Хотя `appVersion` информативна, лучшей практикой в CI/CD является строгая синхронизация и инкрементирование обеих версий.

- **`appVersion`** должна соответствовать версии развертываемого приложения (тегу Docker-образа).
- **`version`** (версия чарта) должна инкрементироваться (обычно `PATCH`) при **любом** изменении, включая:
  - Изменения в шаблонах (`templates/`).
  - Добавление новых параметров в `values.yaml`.
  - **Обновление `appVersion`**.

Этот подход гарантирует, что для каждой версии приложения существует уникальный, неизменяемый артефакт чарта, обеспечивая надежные откаты.

**Практический пример синхронизации:**

```bash
# В CI/CD: инкрементPATCH при каждом коммите
CURRENT_VERSION=$(helm show chart ./my-chart | grep "^version:" | awk '{print $2}')
PATCH=$(echo $CURRENT_VERSION | cut -d. -f3)
NEW_PATCH=$((PATCH + 1))
NEW_VERSION=$(echo $CURRENT_VERSION | cut -d. -f1-2).$NEW_PATCH

# Обновление Chart.yaml
sed -i "s/version:.*/version: $NEW_VERSION/" ./my-chart/Chart.yaml
sed -i "s/appVersion:.*/appVersion: \"$IMAGE_TAG\"/" ./my-chart/Chart.yaml
```

### Версионирование в OCI-репозиториях

В Helm v4 работа с OCI-реестрами является стандартом.

- Тег образа в реестре **должен строго соответствовать** полю `version` в `Chart.yaml`.
- При публикации (`helm push`) Helm автоматически использует версию из манифеста как тег.
- Для обеспечения максимальной надежности в Production рекомендуется использовать **Digest** (хеш образа) вместо тега.

```bash
# Установка по точному дигесту (Immutable Infrastructure)
helm install my-release oci://registry.example.com/charts/my-app@sha256:7f...
```

**Почему Digest надёжнее тега:** Тег `:1.2.3` может быть перезаписан (tag moving), дигест — нет. При обновлении реестра (например, после пересборки чарта с той же версией) дигест остаётся уникальным идентификатором содержимого.

### История, ревизии и Server-Side Apply

В Helm v4 каждая модификация (upgrade/rollback) создаёт новую ревизию, но процесс применения изменений делегируется Kubernetes API через **Server-Side Apply (SSA)**.

1.  **Владение полями (Field Ownership):** Kubernetes отслеживает, какие поля манифеста управляются Helm. Это предотвращает конфликты, если другие контроллеры (например, HPA или Sidecar-инжекторы) изменяют те же ресурсы.
2.  **Ревизии как снапшоты:** Каждая ревизия в Secret хранит полное состояние, что позволяет SSA корректно вычислять патчи при откатах.
3.  **Статусы в истории:**
    - `deployed` — текущая активная версия.
    - `superseded` — предыдущая версия.
    - `failed` — ошибка при деплое.

**Что хранится в Secret ревизии:**
```bash
# Просмотр секрета ревизии
kubectl get secret sh.helm.release.v1.myapp.v3 -n prod -o yaml
# Содержит: name, namespace, version, hooks, manifests, config (values), info (status)
```

### Зависимости и lock-файл

При использовании зависимостей Helm фиксирует точные версии в `Chart.lock`. Этот файл **обязательно** должен находиться под контролем версий (Git).

```bash
# Обновление зависимостей и создание Chart.lock
helm dependency update

# Сборка зависимостей строго по Chart.lock (для CI/CD)
helm dependency build
```

**Разница между `update` и `build`:**
- `helm dependency update` — скачивает актуальные версии зависимостей (по диапазонам SemVer из `Chart.yaml`) и обновляет `Chart.lock`.
- `helm dependency build` — восстанавливает зависимости строго по `Chart.lock`, без обращения к репозиториям. Используется в CI/CD и air-gapped средах.

### Управление глубиной истории

Каждая ревизия хранится как отдельный Secret. При большом количестве ревизий это перегружает etcd и замедляет операции API.

**Как работает `--history-max`:**

```bash
# Ограничение: максимум 10 ревизий
helm upgrade myapp ./chart --history-max 10 -n prod
```

При каждом `upgrade` или `rollback` Helm:
1. Создаёт новую ревизию.
2. Проверяет количество ревизий для данного релиза.
3. Если количество превышает `--history-max`, удаляет **самые старые** ревизии (с наименьшим номером).
4. Ревизии со статусом `deployed` или `failed` **никогда** не удаляются автоматически — удаляются только `superseded`.

> **Рекомендация:** Устанавливайте `--history-max` в диапазоне 10–20. Этого достаточно для диагностики и отката, но не перегружает etcd.

**Установка по умолчанию через переменную окружения:**
```bash
# В CI/CD или .bashrc
export HELM_HISTORY_MAX=10

# При обновлении
helm upgrade myapp ./chart -n prod
# → автоматически применит --history-max 10
```

---

## Практические сценарии

### Просмотр и анализ истории

```bash
# Просмотр последних 10 ревизий
helm history my-release -n prod --max 10

# Детали конкретной ревизии
helm get values my-release -n prod --revision 7   # Пользовательские значения
helm get manifest my-release -n prod --revision 7 # Итоговый рендеринг манифеста

# Показать все значения текущей ревизии (включая дефолтные)
helm get values my-release -n prod --all
```

**Аудит изменений между ревизиями:**
```bash
# Сравнение манифестов двух ревизий (diff)
diff <(helm get manifest myapp --revision 5) <(helm get manifest myapp --revision 6)

# Сравнение значений
diff <(helm get values myapp --revision 5 -o yaml) <(helm get values myapp --revision 6 -o yaml)

# JSON-вывод для парсинга скриптами
helm history my-release -n prod -o json | jq '.[] | select(.status=="failed") | {revision, status, description}'
```

### Безопасный откат (Rollback)

```bash
# Откат к конкретной ревизии
helm rollback my-release 7 -n prod

# Откат к предыдущей успешной версии (0 — последняя рабочая)
helm rollback my-release 0 -n prod

# Откат с ожиданием готовности через kstatus
helm rollback my-release 7 -n prod --wait --timeout 5m

# Принудительный откат (если ресурсы конфликтуют)
helm rollback my-release 7 -n prod --force
```

**Когда использовать `--force`:**
- Предыдущая ревизия содержала ресурсы, которые были изменены вручную (`kubectl edit`, другой контроллер).
- SSA не может корректно вычислить патч из-за изменений владения полями.
- `--force` удаляет ресурсы текущей ревизии и пересоздаёт их из целевой.

**Edge case: откат к удалённой ревизии:**
```bash
# Если --history-max был мал и нужная ревизия удалена
helm history my-release -n prod
# → Ревизии 1-5 отсутствуют (удалены --history-max)

# Ошибка при откате:
# Error: no available release name found

# Решение: откатить к доступной ревизии или пересоздать релиз
helm rollback my-release 6 -n prod  # К доступной ревизии
```

### Автоматизация деплоя и SSA

Для минимизации конфликтов в сложных кластерах используйте флаги SSA:

```bash
# --server-side: принудительное использование SSA (в v4 включено по умолчанию)
# --force-conflicts: перехват владения полями, если они были изменены вручную
helm upgrade --install my-app ./chart \
  --atomic \
  --cleanup-on-fail \
  --server-side \
  --force-conflicts \
  -n prod
```

**Таблица флагов управления деплоем:**

| Флаг | Описание | Когда использовать |
|------|----------|-------------------|
| `--atomic` | Включает `--wait` + автоматический `rollback` при ошибке или timeout. | Production, критичные сервисы. Гарантирует откат при неуспехе. |
| `--wait` | Блокирует завершение команды до Ready всех подов, PVC, LoadBalancer Services. | Всегда рекомендуется для `upgrade`. |
| `--wait-for-jobs` | Дополнительно ждёт завершения Job-хуков (включает `--wait`). | Хуки с миграциями, инициализацией. |
| `--cleanup-on-fail` | Удаляет ресурсы нового релиза при ошибке (предотвращает orphaned resources). | Всегда в паре с `--atomic`. |
| `--timeout <duration>` | Таймаут ожидания готовности (по умолчанию 5m0s). | Увеличьте для больших деплоев (>100 подов). |
| `--force` | Принудительное обновление: пересоздание ресурсов через delete + create. | Конфликты SSA, ручные изменения в кластере. |
| `--force-conflicts` | Перехват владения полей у других контроллеров. | Миграция с Helm v3 на v4, ручные правки. |
| `--reuse-values` | При upgrade переиспользует текущие значения релиза. Новые values из `values.yaml`叠加ляются. | Частичный override без потери текущих настроек. |
| `--reset-values` | Сбрасывает к дефолтным значениям из `values.yaml` чарта. Игнорирует текущие. | Полный сброс конфигурации. |
| `--dependency-update` | Автоматически обновляет зависимости перед деплоем. | Чарты с активными зависимостями. |
| `--create-namespace` | Создаёт namespace если не существует. | Первичная установка. |
| `--history-max <n>` | Ограничивает количество хранимых ревизий. | Всегда; оптимальное значение 10–20. |

**Отличие `--reuse-values` от `--reset-values`:**

```bash
# Текущий релиз установлен с:
# replicas=3, image.tag=v1.0, service.type=ClusterIP

# --reuse-values: переиспользует текущие + overlay
helm upgrade myapp ./chart --reuse-values --set replicas=5
# → replicas=5, image.tag=v1.0, service.type=ClusterIP

# --reset-values: сброс к defaults
helm upgrade myapp ./chart --reset-values --set replicas=5
# → replicas=5, image.tag=<default>, service.type=<default>

# Без флага: переиспользует текущие + overlay ( аналог --reuse-values в v4)
helm upgrade myapp ./chart --set replicas=5
# → replicas=5, image.tag=v1.0, service.type=ClusterIP
```

### Продвижение через окружения (Promotion Pipeline)

Полный пайплайн развертывания от разработки до production:

```bash
# 1. Сборка: bump version в Chart.yaml
NEW_VERSION="1.2.$(($(grep 'version:' Chart.yaml | awk '{print $2}' | cut -d. -f3) + 1))"
sed -i "s/version:.*/version: $NEW_VERSION/" Chart.yaml
sed -i "s/appVersion:.*/appVersion: \"$IMAGE_TAG\"/" Chart.yaml

# 2. Упаковка и публикация
helm package ./my-chart
helm push my-chart-$NEW_VERSION.tgz oci://registry.example.com/charts

# 3. Dev: быстрое тестирование
helm upgrade --install my-app-dev oci://registry.example.com/charts/my-chart \
  --version $NEW_VERSION \
  -f values-dev.yaml \
  --namespace dev \
  --create-namespace \
  --atomic --timeout 5m

# 4. Staging: полноценное тестирование
helm upgrade --install my-app-staging oci://registry.example.com/charts/my-chart \
  --version $NEW_VERSION \
  -f values-staging.yaml \
  --namespace staging \
  --atomic --timeout 10m

# 5. Production: атомарный деплой по.digest (Immutable Promotion)
HELM_DIGEST=$(helm show chart oci://registry.example.com/charts/my-chart --version $NEW_VERSION 2>/dev/null | grep digest | awk '{print $2}')
helm upgrade --install my-app oci://registry.example.com/charts/my-chart@$HELM_DIGEST \
  -f values-prod.yaml \
  --namespace prod \
  --atomic --timeout 15m \
  --wait --wait-for-jobs \
  --history-max 10
```

### Проверка изменений перед обновлением

```bash
# Дифф изменений (требуется плагин helm-diff, доступен как WASM в v4)
helm diff upgrade myapp ./chart -n prod

# Сравнение манифестов двух ревизий
diff <(helm get manifest myapp --revision 5) <(helm get manifest myapp --revision 6)

# Dry-run в кластере (v4: Server-side dry-run, точнее проверяет права и схемы)
helm upgrade --install my-app ./chart -f values-prod.yaml --dry-run --debug -n prod
```

### Диагностика состояния релиза

**Быстрая проверка здоровья:**
```bash
# Статус с деталями
helm status my-release -n prod --show-details

# Просмотр Event'ов
kubectl get events -n prod --field-selector involvedObject.name=my-release --sort-by='.lastTimestamp'

# Все ресурсы релиза
kubectl get all -l app.kubernetes.io/instance=my-release -n prod

# Проблемные Pod'ы
kubectl get pods -l app.kubernetes.io/instance=my-release -n prod \
  --field-selector=status.phase!=Running,status.phase!=Succeeded
```

**Диагностика `failed`-состояния:**
```bash
# 1. Последняя ошибка
helm history my-release -n prod --max 5

# 2. Логи Pod'ов (если это Deployment/StatefulSet)
kubectl logs -l app.kubernetes.io/name=my-release -n prod --tail=100

# 3. События хуков (если ошибка в хуке)
kubectl get jobs -l app.kubernetes.io/instance=my-release -n prod
kubectl logs job/<hook-job-name> -n prod

# 4. Конфликты SSA (v4)
kubectl get deployment my-release -n prod -o jsonpath='{.metadata.managedFields}' | jq .
```

**Восстановление из `failed`-состояния:**
```bash
# Вариант 1: Откат к последней рабочей ревизии
helm rollback my-release 0 -n prod

# Вариант 2: Принудительное обновление
helm upgrade --install my-release ./my-chart \
  -f values-prod.yaml -n prod \
  --force --cleanup-on-fail

# Вариант 3: Полная пересоздание (самый надежный)
helm uninstall my-release -n prod --keep-history
helm install my-release ./my-chart \
  -f values-prod.yaml -n prod --atomic
```

### Восстановление Helm-релизов без GitOps

В средах без GitOps-инструментов (Argo CD, Flux) или при полной потере кластера/реестра восстановление Helm-релиза выполняется вручную. Ключевое отличие от GitOps: источником правды является **локальный чарт + OCI-репозиторий/Helm repo**, а не Git-репозиторий с манифестами. Это расширяет поверхность ошибок, но при наличии чарта, истории ревизий и значений восстановление возможно.

---

#### Предпосылки для восстановления

| Компонент | Где хранится | Что нужно для восстановления |
|-----------|--------------|-------------------------------|
| **Шаблоны чарта** | Файловая система / OCI / HTTP repo | Доступ к исходному чарту той же версии |
| **Значения релиза** | Secret `sh.helm.release.v1.<name>.v<N>` | `helm get values <release> --revision N` |
| **Манифесты релиза** | Secret ревизии | `helm get manifest <release> --revision N` |
| **Версия чарта** | OCI tag / `Chart.yaml` | Точная версия для `helm install --version` |
| **Секреты приложения** | Kubernetes Secrets, Vault, sealed-secrets | Отдельный бэкап; Helm не управляет ими |

> **Важно:** Helm хранит только манифесты и значения релиза в Secret'е. Секреты приложения (`Secret`, `SealedSecret`, Vault) **не** восстанавливаются через Helm. Их бэкап — отдельная задача.

---

#### Сценарий 1: Релиз удалён, но история сохранена

Если релиз был удалён без `--keep-history`, все Secret'ы ревизий удалены. Если же `--keep-history` использовался, восстановление возможно напрямую.

```bash
# 1. Проверить, присутствует ли релиз
helm list -A | grep my-release
# → нет записи

# 2. Проверить, остались ли Secrets ревизий
kubectl get secret -n prod | grep sh.helm.release.v1.my-release
# → sh.helm.release.v1.my-release.v3

# 3. Получить последние значения и манифесты
helm get values my-release -n prod --revision 3 --all > /tmp/values-restore.yaml
helm get manifest my-release -n prod --revision 3 > /tmp/manifest-restore.yaml

# 4. Установить релиз заново с сохранением истории
helm upgrade --install my-release ./my-chart \
  -n prod \
  -f /tmp/values-restore.yaml \
  --version 1.2.3 \
  --history-max 10 \
  --atomic --timeout 10m
```

**Когда используется:** Аварийное удаление релиза (`helm uninstall` без `--keep-history`), но ревизии ещё не вышли за `--history-max`.

---

#### Сценарий 2: Релиз и история удалены, есть только чарт

Самый частый сценарий при потере кластера или `--history-max` слишком мал.

```bash
# 1. Проверить доступность чарта
helm repo list
helm search repo my-chart --version 1.2.3

# 2. Найти подходящий набор значений
# Вариант A: Если values.yaml хранился в Git/CI/CD артефактах
# Вариант B: Собрать из текущего production-окружения
helm show values oci://registry.example.com/charts/my-chart --version 1.2.3 \
  | sed 's/^#.*//' | sed '/^$/d' > /tmp/values.yaml

# 3. Установить релиз
helm upgrade --install my-release oci://registry.example.com/charts/my-chart \
  --version 1.2.3 \
  -f /tmp/values.yaml \
  -n prod --create-namespace \
  --atomic --timeout 15m --wait --wait-for-jobs
```

**Когда используется:** Полная потеря кластера, миграция на новый кластер, восстановление после катастрофы без GitOps.

---

#### Сценарий 3: Потеря реестра OCI, есть локальный чарт

```bash
# 1. Упаковать локальный чарт
helm package ./my-chart --version 1.2.3
# → my-chart-1.2.3.tgz

# 2. Использовать локальный файл вместо OCI
helm upgrade --install my-release ./my-chart-1.2.3.tgz \
  -f values-prod.yaml \
  -n prod --atomic --timeout 15m
```

---

#### Сценарий 4: Ручное восстановление из произвольных значений и манифестов

Если ни чарта, ни истории нет, но известны итоговые манифесты (например, экспортированы через `helm get manifest` до инцидента), можно использовать `helm install --dry-run` для валидации, а затем применить манифесты напрямую через `kubectl apply`.

```bash
# ВАЖНО: Это уже не Helm-управляемый релиз, а "сырые" ресурсы.
# Helm не будет отслеживать их состояние.

# 1. Применить манифесты напрямую
kubectl apply -f manifest-restore.yaml -n prod

# 2. Создать label для идентификации ресурсов релиза
kubectl label deployment my-release app.kubernetes.io/managed-by=Helm -n prod

# 3. (Опционально) Зарегистрировать релиз в Helm-истории вручную
# Helm не поддерживает импорт истории, но можно создать dummy-secret:
kubectl create secret generic sh.helm.release.v1.my-release.v1 \
  --from-literal=release="<base64-json>" \
  -n prod
```

**Когда используется:** Экстремальный случай, когда восстановить Helm-релиз невозможно, но необходимо быстро поднять приложение.

---

#### Сценарий 5: Восстановление после потери namespace

```bash
# Namespace удалён вместе со всеми ресурсами и Secret'ами релиза

# 1. Создать namespace
kubectl create namespace prod

# 2. Восстановить секреты приложения из отдельного бэкапа (не Helm)
kubectl apply -f app-secrets-backup.yaml -n prod

# 3. Установить релиз
helm upgrade --install my-release ./my-chart \
  -f values-prod.yaml \
  -n prod --atomic --timeout 15m
```

---

#### Восстановление приложения после полной потери кластера

```bash
# Предполагается: есть резервная копия values.yaml и доступ к OCI

# Шаг 1: Восстановление нового кластера (зависит от инфраструктуры)
# Например, через terraform / cloud provider console / kubeadm

# Шаг 2: Настройка kubectl
aws eks update-kubeconfig --name prod-cluster --region eu-west-1

# Шаг 3: Восстановление namespace
kubectl create namespace prod

# Шаг 4: Восстановление CRD (если используются)
helm show crds ./my-chart | kubectl apply -f -

# Шаг 5: Установка релиза
helm upgrade --install my-release oci://registry.example.com/charts/my-chart \
  --version 1.2.3 \
  -f values-prod.yaml \
  -n prod \
  --atomic --timeout 15m --wait --wait-for-jobs \
  --history-max 10
```

**RTO/RPO при отсутствии GitOps:**
| Компонент | RPO | RTO | Метод восстановления |
|-----------|-----|-----|----------------------|
| Манифесты | 0 | <5 мин | Helm chart в OCI + `helm upgrade --install` |
| Значения релиза | До коммита | <5 мин | `helm get values` из истории / Git артефакты |
| Секреты приложения | Зависит от расписания | <30 мин | Vault / sealed-secrets / отдельный бэкап |
| CRD | 0 | <5 мин | `helm show crds` + `kubectl apply` |

---

#### Практические рекомендации

1. **`--keep-history` при удалении:** Всегда используйте `helm uninstall --keep-history` при возможном восстановлении. Это сохраняет Secret'ы ревизий.
2. **Бэкап `values.yaml`:** Храните production-значения отдельно от чарта (Git-репозиторий, S3, Vault).
3. **Ограничение `--history-max`:** Устанавливайте значение 10–20, чтобы балансировать между сохранением истории и нагрузкой на etcd.
4. **Immutable OCI:** Публикуйте чарты с тегом, соответствующим SemVer, и разворачивайте по Digest (`@sha256:...`), чтобы избежать drift версий.
5. **Документирование версии чарта:** В production ведите журнал версий чартов (`Chart.yaml: version`), чтобы при восстановлении точно знать, какая версия использовалась.
6. **Тестирование восстановления:** Раз в квартал выполняйте drill: удаляйте релиз и восстанавливайте его в тестовом namespace. Это проверит доступность чарта и целостность values.

---

#### Типичные ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Error: release: not found` | Релиз удалён, история очищена | Восстановить через `helm upgrade --install` с нужными значениями |
| `Error: no available release name found` | `--history-max` слишком мал, нужная ревизия удалена | Установить заново или найти ближайшую доступную ревизию |
| `Error: rendered manifests contain a resource that already exists` | Часть ресурсов осталась в кластере после неудачного удаления | `kubectl delete` оставшихся ресурсов или `helm upgrade --install --force` |
| `Error: UPGRADE FAILED: cannot re-use a name that is still in use` | Release name занят в другом namespace | `helm list -A`; удалить/переименовать конфликтующий релиз |
| Потеря секретов приложения | Helm не управляет `Secret` с учётными данными | Восстанавливать из отдельного бэкапа Vault/sealed-secrets |

---

#### См. также

- [Обзор Helm](./helm_overview.md) — архитектура v4, SSA и kstatus.
- [Команды и рабочий процесс Helm](./helm_commands_and_workflow.md) — детальный разбор жизненного цикла.
- [Паттерны и устранение неисправностей Helm](./Advanced/patterns_troubleshooting.md) — восстановление зависших релизов и edge cases.
- [GitOps: обзор методологии](../GitOps/GitOps_overview.md) — автоматическое восстановление через Argo CD / Flux.
- [Disaster Recovery (концепции)](../../Concepts/disaster_recovery.md) — общие стратегии аварийного восстановления для Kubernetes.

---

## Дополнительная информация

### Безопасность и проверка целостности

Для подтверждения подлинности и целостности версий чартов используются **файлы доказательств (Provenance files)**:

1.  **Ключ GnuPG:** Автор чарта подписывает пакет своим приватным ключом.
2.  **Файл `.prov`:** Содержит контрольную сумму (SHA-256) файла `.tgz` и цифровую подпись.
3.  **Проверка:** При установке Helm может автоматически проверять подпись.

```bash
# Установка с проверкой подписи
helm install my-release my-chart-1.2.3.tgz --verify --keyring ~/.gnupg/pubring.gpg

# Подписание при упаковке
helm package ./my-chart --sign --key releng@company.com --keyring ~/.gnupg/secring.gpg
```

### CRD и жизненный цикл релиза

CRD (CustomResourceDefinitions) имеют особый жизненный цикл в Helm v4:

- CRD из директории `crds/` **не подлежат откату** через `helm rollback`. Они остаются в кластере после удаления релиза.
- При `helm upgrade` новые CRD добавляются, но существующие **не обновляются**.
- Для обновления CRDrequires`kubectl apply` или внешний контроллер (Cert-Manager, Istio).

```bash
# Проверка CRD перед установкой
helm show crds my-chart | kubectl apply -f -

# Обновление CRD отдельно от чарта
kubectl apply -f my-chart/crds/ --server-side
```

### SCM-интеграция: Git Tags → Chart Version → OCI Digest

Полный трекинг от коммита до артефакта:

```bash
# 1. Git tag → версия чарта
GIT_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "0.1.0")
# → v1.2.3

# 2. Удаление префикса v для SemVer
CHART_VERSION=${GIT_TAG#v}
# → 1.2.3

# 3. Обновление Chart.yaml
sed -i "s/version:.*/version: $CHART_VERSION/" Chart.yaml

# 4. Упаковка, подписание, публикация
helm package ./my-chart --version $CHART_VERSION
helm push my-chart-$CHART_VERSION.tgz oci://registry.example.com/charts

# 5. Получение digest для Immutable Deploy
DIGEST=$(helm show chart oci://registry.example.com/charts/my-chart --version $CHART_VERSION 2>&1 | grep "digest:" | awk '{print $2}')

# 6. Deploy по digest
helm upgrade --install my-app oci://registry.example.com/charts/my-chart@$DIGESTAMP
```

### Рекомендации

- **Фиксация версий (Pinning):** Всегда указывайте конкретную версию `--version X.Y.Z` в автоматизации.
- **Атомарность:** Флаг `--atomic` — лучший способ предотвратить зависание релиза в статусе `failed`.
- **Контроль истории:** Устанавливайте `--history-max` в диапазоне 10–20 ревизий.
- **Chart.lock:** Всегда фиксируйте зависимости, чтобы избежать "дрейфа" версий при сборке.
- **Использование Digest:** В критических окружениях ссылайтесь на OCI-чарты по хешу (`@sha256:...`).
- **Пре-релизы:** Используйте `--devel` для установки alpha/beta/rc версий в dev/staging.
- **Audit trail:** Сохраняйте вывод `helm diff` как артефакт CI/CD для compliance.
- **Одно имя релиза на namespace:** Избегайте дублирования имён релизов в одном namespace.

### Частые ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `another operation (install/upgrade/rollback) is in progress` | Предыдущая операция не завершена | Дождитесь завершения или `helm rollback` к предыдущей ревизии |
| `no available release name found` | `--history-max` слишком мал, нужная ревизия удалена | Откатить к доступной ревизии или пересоздать релиз |
| `UPGRADE FAILED: timed-out` | Ресурсы не стали Ready за timeout | Увеличьте `--timeout`, проверьте readiness probes |
| `UPGRADE FAILED: release: fails, normalized diff is empty` | Конфликт SSA, несовместимые поля | Используйте `--force-conflicts` или `--force` |
| `release: not found` | Релиз был удалён или находится в другом namespace | Проверьте `helm list -A`, убедитесь в правильном `-n` |

### См. также

- [Обзор Helm](./helm_overview.md) — архитектура v4, SSA и kstatus.
- [Команды и рабочий процесс Helm](./helm_commands_and_workflow.md) — детальный разбор жизненного цикла.
- [Структура Helm-чарта](./helm_chart_structure.md) — изучение `Chart.yaml` и `apiVersion`.
- [Плагины Helm](./helm_plugins.md) — работа с `helm-diff` и WASM-расширениями.
- [Мониторинг Helm-релизов](./helm_monitoring_observability.md) — Prometheus, Grafana и алертинг для релизов.
