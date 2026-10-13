# Argo CD — волны синхронизации (Sync Waves) и хуки (Hooks)

**Актуально для:** Argo CD v3.4.x / master. Версионные отличия: PostDelete — с v2.10, PreDelete — с v3.3, comma-separated `hook-delete-policy` — с v2.10, `syncOverrun` (взаимодействие с Sync Windows) — с v3.5.

## Предварительные требования

Перед настройкой волн и хуков необходимо убедиться в следующем:

1. **Версия Argo CD:** базовые волны и хуки (PreSync, Sync, Skip, PostSync, SyncFail) доступны в любой поддерживаемой версии. Для PostDelete необходима v2.10+, для PreDelete — v3.3+.
2. **Argo CD Application Controller:** активен и работает (именно он применяет ресурсы и выполняет хуки).
3. **Понимание Sync Waves:** базовое понимание аннотации `argocd.argoproj.io/sync-wave` и порядка применения ресурсов.
4. **Понимание Hooks:** базовое понимание аннотации `argocd.argoproj.io/hook` и фаз жизненного цикла.
5. **Health Checks:** базовое понимание проверок здоровья Argo CD. Для кастомных проверок требуется опыт написания Lua-скриптов.
6. **Kubernetes Jobs:** понимание работы Kubernetes Jobs (`backoffLimit`, `activeDeadlineSeconds`) для настройки хуков.

## Определения

**Волна синхронизации (Sync Wave)** — целочисленная аннотация `argocd.argoproj.io/sync-wave`, группирующая ресурсы в последовательные этапы применения. Переход к следующей волне возможен только после достижения статуса `Healthy` всеми ресурсами текущей волны.

**Хук (Hook)** — ресурс (обычно Job или Pod) с аннотацией `argocd.argoproj.io/hook`, выполняемый на определённой фазе жизненного цикла синхронизации или удаления приложения.

**Health Gating (барьер здоровья)** — принцип работы волн: контроллер блокирует переход к следующей волне, пока текущая не станет полностью `Healthy`. Ресурсы без встроенной проверки здоровья (ConfigMap, Secret, ServiceAccount) считаются `Healthy` сразу после применения.

**Hook Delete Policy** — политика автоматической очистки ресурсов хука (`argocd.argoproj.io/hook-delete-policy`): `HookSucceeded`, `HookFailed`, `BeforeHookCreation`.

**PreDelete** — (v3.3+) хук, выполняемый перед удалением ресурсов приложения. Только при полном удалении Application, не при обычной синхронизации (даже с включённым prune).

**PostDelete** — (v2.10+) хук, выполняемый после удаления всех ресурсов приложения.

**Sync Overrun** — (v3.5+) разрешение уже запущенной синхронизации дойти до конца при выходе за границы разрешённого Sync Window (см. [Sync Windows](./sync_windows.md)).

## Базовые концепции

### Механика волн синхронизации

Управляется аннотацией `argocd.argoproj.io/sync-wave`:

- **Значение:** любое целое число (положительное, отрицательное или ноль), передаётся как строка (`"-10"`, `"0"`, `"10"`).
- **Значение по умолчанию:** `0` — ресурсы без аннотации и хуки попадают в волну 0.
- **Порядок выполнения:** ресурсы с наименьшим числовым значением применяются первыми; отрицательные волны позволяют выполнить ресурс до всех остальных.
- **Одна волна:** ресурсы с одинаковым значением применяются параллельно.
- **Fallback:** если аннотация `sync-wave` present, но не является числом, Argo CD использует аннотацию Helm `helm.sh/hook-weight` (для Helm-чартов); если и её нет — волна 0.
- **Sparse Numbering (разреженная нумерация):** рекомендуется использовать шаг (например, `-10`, `0`, `10`), чтобы иметь возможность вставить промежуточные ресурсы без изменения всего набора манифестов.

### Порядок применения ресурсов (precedence)

При синхронизации Argo CD упорядочивает все ресурсы приложения по четырём ключам (по возрастанию приоритета):

1. **Фаза** (PreSync → Sync → PostSync; при сбое — SyncFail; при удалении — PreDelete/PostDelete)
2. **Волна** (меньшее значение первым)
3. **Kind** (сначала Namespace, затем прочие ресурсы Kubernetes, затем Custom Resources)
4. **Имя** ресурса

> [!IMPORTANT]
> **Приоритет: Фаза главнее Волны (Phase outranks Wave):**
> Фазы выполняются строго последовательно. Любой хук фазы `PreSync` (даже с волной `10` или `100`) **всегда выполнится раньше**, чем любой манифест фазы `Sync` (даже с отрицательной волной `-10`). Внутри каждой фазы ресурсы сортируются по номеру волны.

**Поведение ресурсов без встроенного Health Check:**
Объекты, не имеющие поля `status` или встроенной логики оценки здоровья (`ConfigMap`, `Secret`, `ServiceAccount`, `NetworkPolicy`), признаются контроллером `Healthy` мгновенно в момент успешного применения API-сервером. Контроллер не ожидает и сразу переходит к следующей волне (с учетом `ARGOCD_SYNC_WAVE_DELAY`).

Алгоритм применения волн:

1. Контроллер определяет **первую применяемую волну** — это первый номер волны, в которой есть хотя бы один out-of-sync или нездоровый ресурс.
2. Применяются все ресурсы этой волны.
3. Контроллер ожидает, пока все ресурсы волны станут `Healthy` (Health Gating).
4. Процесс повторяется до тех пор, пока все фазы и волны не станут in-sync и healthy.

> [!WARNING]
> Если в первой волне есть ресурс, который никогда не станет `Healthy`, приложение не сможет достичь состояния `Healthy` — все последующие волны заблокированы.

### Задержка между волнами

Между волнами контроллер выдерживает паузу (по умолчанию **2 секунды**), чтобы другие контроллеры успели отреагировать на только что применённый spec, и чтобы Argo CD не оценивал здоровье ресурса по устаревшему объекту (что может преждевременно запустить хуки следующей волны). Задержка настраивается переменной окружения `ARGOCD_SYNC_WAVE_DELAY` (в секундах) на Deployment/StatefulSet контроллера приложений:

```yaml
# manifests/base/application-controller-deployment/argocd-application-controller-deployment.yaml
env:
- name: ARGOCD_SYNC_WAVE_DELAY
  value: "5"
```

> [!NOTE]
> Задержка не является надёжной защитой от преждевременной оценки здоровья. Надёжное решение — custom health check, проверяющий `status.observedGeneration == metadata.generation`.

### Жизненный цикл хуков

Хуки настраиваются аннотацией `argocd.argoproj.io/hook`. Хук может быть любым Kind, но обычно это Pod, Job или Argo Workflow. В аннотации допустим список фаз через запятую.

| Фаза | Описание | Типичное применение |
| :--- | :--- | :--- |
| **PreSync** | Выполняется до применения манифестов. Если хотя бы один PreSync-хук завершился неуспешно, вся синхронизация останавливается и помечается failed. | Миграции схемы БД, проверки предусловий. |
| **Sync** | Выполняется после успешного завершения всех PreSync-хуков, одновременно с применением манифестов. Сбой любого Sync-хука помечает синхронизацию failed (и запускает SyncFail-хуки). | Сложная оркестрация, не укладывающаяся в rolling-update стратегию. |
| **Skip** | Ресурс не применяется при синхронизации. | Исключение ресурса из GitOps-цикла (например, mutating admission webhook, ломающий sync). |
| **PostSync** | Выполняется после успешного завершения всех Sync-хуков, успешного применения манифестов и перехода всех ресурсов в `Healthy`. Сбой помечает синхронизацию failed. | Smoke-тесты, интеграционные проверки, уведомления. |
| **SyncFail** | Выполняется при неудачной синхронизации (доступна с v1.2). Если сам SyncFail-хук завершается неуспешно, Argo CD не предпринимает дополнительных действий, кроме пометки операции failed. | Очистка, сбор логов сбоя, оповещения. |
| **PreDelete** | (v3.3+) Выполняется перед удалением ресурсов приложения — только при полном удалении Application (`kubectl delete application`, `argocd app delete`), не при обычной синхронизации даже с prune. | Снапшоты БД, отзыв сертификатов, уведомления. |
| **PostDelete** | (v2.10+) Выполняется после удаления всех ресурсов приложения. | Удаление DNS-записей, внешних ресурсов, уведомления. |

**Как работают фазы (алгоритм синхронизации):**

1. Применить все ресурсы с аннотацией PreSync. При сбое любого — весь процесс останавливается и помечается failed.
2. Применить все ресурсы с аннотацией Sync (одновременно с основными манифестами). При сбое любого — синхронизация failed, запускаются SyncFail-хуки.
3. Применить все ресурсы с аннотацией PostSync (после того как все ресурсы `Healthy`). При сбое любого — синхронизация failed.

Ресурсы с аннотацией Skip не применяются.

> [!IMPORTANT]
> **Хуки не выполняются при селективной синхронизации** (`--resource`/`--label`) и при `argocd app sync --strategy apply` — хук-ресурсы не применяются и не выполняются. Подробнее — в разделе о взаимодействии с ручным синком.

### Именованные хуки и generateName

Хук с явным `metadata.name` создаётся **один раз** — при повторных синхронизациях он не пересоздаётся. Чтобы хук пересоздавался при каждой синхронизации, используйте либо политику `BeforeHookCreation`, либо `metadata.generateName` (суффикс будет генерироваться автоматически).

### Очистка хуков (hook-delete-policy)

Политика задаётся аннотацией `argocd.argoproj.io/hook-delete-policy` (список через запятую поддерживается с v2.10):

| Политика | Описание | Рекомендация |
| :--- | :--- | :--- |
| **HookSucceeded** | Ресурс хука удаляется после успешного завершения (для Job/Workflow — после успешного completion). | Для успешных запусков. |
| **HookFailed** | Ресурс хука удаляется после неуспешного завершения. | Отладка. |
| **BeforeHookCreation** | Существующий ресурс хука удаляется перед созданием нового (с v1.3). Предназначен для использования с `metadata.name`. | Рекомендуется для именованных хуков. |

**Важно:** если политика не указана, Argo CD автоматически применяет правила `BeforeHookCreation`.

> [!WARNING]
> Не используйте `ttlSecondsAfterFinished` на Job-хуках (и `ttlStrategy` на Workflow-хуках): Argo CD должен прочитать Job, чтобы определить результат фазы; если Kubernetes удалит Job первым, синхронизация может зависнуть в ожидании уже удалённого хука. Для очистки используйте `hook-delete-policy`.

### PreDelete и PostDelete хуки

**PreDelete (v3.3+)** выполняется при удалении Application:

1. При удалении Application Argo CD ищет PreDelete-хуки в манифестах.
2. Если они есть — создаёт и выполняет их **до** удаления ресурсов приложения.
3. Argo CD ожидает, пока все PreDelete-хуки станут `Healthy`.
4. После успешного завершения хуки очищаются, ресурсы приложения удаляются.

**Сбой PreDelete-хука блокирует удаление:**

- Application остаётся в состоянии deleting с условием (condition) `DeletionError`;
- ресурсы приложения не удаляются, пока хук не завершится успешно;
- исправить хук в Git — Argo CD автоматически повторит удаление на следующем проходе сверки;
- либо вручную удалить сбойный ресурс хука, чтобы удаление продолжилось.

**PostDelete (v2.10+)** выполняется после удаления всех ресурсов приложения:

1. Ресурсы приложения удаляются первыми.
2. После полного удаления создаются и выполняются PostDelete-хуки.
3. Argo CD ожидает `Healthy` всех PostDelete-хуков, затем очищает их.

**Сбой PostDelete-хука:** Application уже удалён из кластера, но CR Application остаётся с условием `DeletionError`. Исправление — через Git (повтор на следующей сверке) или ручное удаление ресурса хука. Обратите внимание: PostDelete-хуки удаляются только если политика удаления соответствует агрегированному статусу хуков удаления — они не собираются мусором после удаления приложения.

### Взаимодействие фаз и волн

Волны и хуки дополняют друг друга: фазы задают грубый порядок (до/во время/после), волны — точный порядок ресурса внутри фазы. Хук может иметь и аннотацию фазы, и аннотацию волны — тогда внутри своей фазы он применяется в заданной волне.

### Теория: как оцениваются хуки-Job

- Pod с `restartPolicy: Never`/`OnFailure` считается `Progressing` во время выполнения и `Healthy` только после успешного завершения — это сделано намеренно, потому что такие Pods обычно используются как хуки и должны завершиться до признания приложения `Healthy`.
- Арго CD оценивает успех фазы **по ресурсу хука**: Job с exit code 0 помечает фазу успешной, и следующие волны запускаются — даже если внешнее состояние (например, БД) оказалось не тем, что ожидает приложение. Если нужно гейтировать фазу на реальном состоянии, используйте CR с контроллером и [кастомной проверкой здоровья](#сценарий-3-кастомный-health-check-для-crd-lua).
- Синхронизация остаётся открытой, пока выполняется хук; статус приложения — `Progressing`. Долгий хук может упереться в таймаут синхронизации (`--sync-timeout`), а принудительная остановка операции **не останавливает** уже запущенный хук.
- **Хуки выполняются при каждой синхронизации**, а не только при изменении самих хуков: self-heal, ручной синк из UI или изменение не связанной части Application запустят их снова. Хуки должны быть идемпотентны и безопасны для повторного запуска.
- PreSync-хук применяется **до** Secret/ConfigMap/ServiceAccount того же Application: хук, читающий пароль из Secret этого же приложения, получит старое значение или упадёт, если Secret ещё не создан. Держите учётные данные хуков вне Application или сделайте Secret хуком с меньшей волной.

## Взаимодействие с другими механизмами

### Sync Waves и Sync Windows

Окна синхронизации ([Sync Windows](./sync_windows.md)) проверяются **при старте операции** (до PreSync-хуков) и **на каждом проходе контроллера во время операции** — окно не проверяется «на волну», но и не игнорируется после старта:

- Если окно закрылось во время выполняющейся синхронизации **без** `syncOverrun`, операция **приостанавливается** (контроллер ставит сообщение `Sync operation blocked by sync window`) и возобновляется, когда окно снова разрешит синхронизацию. Она не прерывается и не откатывается.
- С `syncOverrun: true` (v3.5+, должно быть включено на **всех** подходящих окнах) операция идёт до конца.

**Важно:** длинный деплой с несколькими волнами (или долгий PreSync-хук) может пережить своё окно только при `syncOverrun: true`; иначе он зависнет на границе окна.

### Sync Waves и Auto Sync

Автоматическая синхронизация ([Auto Sync](./auto_sync.md)) учитывает Sync Waves — ресурсы применяются в порядке аннотаций `argocd.argoproj.io/sync-wave`. Если PreSync-хук завершается неуспешно, синхронизация прерывается и применяется политика retry ко всей операции. Зависшая операция (например, зависший хук) блокирует применение новых изменений до завершения или принудительной остановки (`argocd app terminate-op <name>`).

### Sync Waves и Manual Sync

Ручная синхронизация ([Manual Sync](./manual_sync.md)) также учитывает Sync Waves. Управление хуками:

```bash
# Обычный (полный) синк: PreSync-хуки -> применение ресурсов -> PostSync-хуки
argocd app sync my-app

# --strategy apply: хук-аннотированные ресурсы не применяются и не выполняются
argocd app sync my-app --strategy apply

# --strategy hook (дефолт): обычное поведение, хуки выполняются
argocd app sync my-app --strategy hook

# Селективная синхронизация: хуки НЕ выполняются, применяются только выбранные ресурсы
argocd app sync my-app --resource apps:Deployment:api-server
```

> [!NOTE]
> Отдельных флагов `--hooks`/`--hooks-only` у `argocd app sync` нет. `--strategy` принимает только два значения: `apply` (ресурсы без хуков) и `hook` (по умолчанию, хуки включены).

### Sync Waves и Progressive Sync

Прогрессивная синхронизация ([Progressive Sync](./progressive_sync.md)) работает на уровне приложений, а Sync Waves — на уровне ресурсов внутри приложения. Механизмы дополняют друг друга:

- **Волны:** порядок ресурсов *внутри* одного приложения (Namespace → Deployment → Service → Ingress).
- **Progressive Sync:** порядок *между* приложениями (Canary → Staging → Production).

При движении от Canary к Staging контроллер ApplicationSet сначала дождётся `Healthy` для всех приложений Canary, затем запустит синхронизацию для Staging; внутри каждого приложения ресурсы применяются в порядке Sync Waves.

### Sync Waves и Ignore Differences

Игнорирование различий ([Ignore Differences](../ignore_differences.md)) влияет только на обнаружение дрейфа (вычисление OutOfSync), но **не на оценку здоровья**: волны продолжают ждать `Healthy` независимо от `ignoreDifferences`. Игнорируемое поле не может «разблокировать» волну.

### Sync Waves и SelfHeal/Prune

`selfHeal` не применяет отдельные ресурсы вразрез с волнами: при обнаружении дрейфа контроллер запускает **новую операцию синхронизации**, которая применяет ресурсы в стандартном порядке фаз и волн. `prune` удаляет лишние ресурсы в **обратном** порядке волн (см. ниже).

**Важно:** при prune порядок волн реверсируется — ресурсы из более высоких волн удаляются первыми. Если удаление ресурса в волне завершается неуспешно, операция помечается failed, а ресурсы из более низких волн не обрабатываются — зависимые ресурсы удаляются в правильном порядке.

### Hooks и Retry

Политика retry ([Auto Sync — retry](./auto_sync.md)) применяется к синхронизации в целом, включая хуки: если PreSync-хук завершается неуспешно, retry повторяет всю операцию до достижения `limit`. Retry **не ограничивает время выполнения** — для этого используйте `--timeout` при синхронизации (`argocd app sync --timeout <сек>`, по умолчанию 0 = без таймаута) и `activeDeadlineSeconds` на Job-хуке. Пока операция не завершена (например, зависший хук), новый retry не запускается.

## Практические сценарии

### Сценарий 1: Инфраструктурная пирамида (Sync Waves)

Обеспечение готовности базы до запуска приложения. Разреженная нумерация (`-10`, `-5`, `0`) оставляет место для промежуточных ресурсов.

```yaml
# 1. Приоритетный ресурс (Namespace) - Волна -10
apiVersion: v1
kind: Namespace
metadata:
  name: my-stack
  annotations:
    argocd.argoproj.io/sync-wave: "-10"
---
# 2. Инфраструктура (ConfigMaps, Secrets, Operator CRs) - Волна -5
apiVersion: v1
kind: ConfigMap
metadata:
  name: db-config
  namespace: my-stack
  annotations:
    argocd.argoproj.io/sync-wave: "-5"
---
# 3. Приложение (Deployment, Service) - Волна 0 (default)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
  namespace: my-stack
```

### Сценарий 2: Миграция базы данных с безопасной очисткой

`BeforeHookCreation` гарантирует отсутствие конфликтов имён Job при повторных синхронизациях, а `HookSucceeded` удаляет Job после успеха. Список политик через запятую поддерживается с v2.10.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
    argocd.argoproj.io/sync-wave: "-1"
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 900
  template:
    spec:
      containers:
      - name: migrate
        image: migrations-tool:v2.4
        envFrom: [{configMapRef: {name: db-config}}]
      restartPolicy: Never
```

### Сценарий 3: Кастомный Health Check для CRD (Lua)

По умолчанию Argo CD не имеет встроенной проверки здоровья для произвольных CRD (ресурс считается `Progressing`, пока не появится статус). Для работы волн с операторами добавьте скрипт в `argocd-cm`. Пример — официальный скрипт для `cert-manager.io/Certificate`:

```yaml
data:
  resource.customizations.health.cert-manager.io_Certificate: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.conditions ~= nil then
        for i, condition in ipairs(obj.status.conditions) do
          if condition.type == "Ready" and condition.status == "False" then
            hs.status = "Degraded"
            hs.message = condition.message
            return hs
          end
          if condition.type == "Ready" and condition.status == "True" then
            hs.status = "Healthy"
            hs.message = condition.message
            return hs
          end
        end
      end
    end

    hs.status = "Progressing"
    hs.message = "Waiting for certificate"
    return hs
```

Допустимые статусы: `Healthy`, `Progressing`, `Degraded`, `Suspended` (по умолчанию — `Progressing`). Формат ключа: `resource.customizations.health.<group>_<kind>`; для core-ресурсов (без API group) — `resource.customizations.health.<Kind>`. Стандартные библиотеки Lua отключены по умолчанию (включаются через `resource.customizations.useOpenLibs.<group>_<kind>: true`). Тот же принцип применяется к CRD операторов (Zalando PostgresOperator, CloudNativePG и т. п.) — скрипт пишется под `status` конкретного CRD.

### Сценарий 4: PreDelete и PostDelete хуки

Безопасное удаление внешних ресурсов (БД, DNS) при удалении приложения. PreDelete требует Argo CD v3.3+, PostDelete — v2.10+.

```yaml
# PreDelete: снапшот БД перед удалением ресурсов (v3.3+)
apiVersion: batch/v1
kind: Job
metadata:
  name: db-snapshot
  annotations:
    argocd.argoproj.io/hook: PreDelete
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 1800
  template:
    spec:
      containers:
      - name: snapshot
        image: postgres:15
        command: ["pg_dump", "-U", "postgres", "-d", "mydb", "-F", "c", "-f", "/backup/snapshot.dump"]
        volumeMounts:
        - name: backup
          mountPath: /backup
      volumes:
      - name: backup
        persistentVolumeClaim:
          claimName: db-backup-pvc
      restartPolicy: Never
---
# PostDelete: удаление DNS-записи после удаления ресурсов (v2.10+)
apiVersion: batch/v1
kind: Job
metadata:
  name: dns-cleanup
  annotations:
    argocd.argoproj.io/hook: PostDelete
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
spec:
  backoffLimit: 1
  template:
    spec:
      containers:
      - name: cleanup
        image: bitnami/kubectl:latest
        command: ["kubectl", "delete", "dnsrecord", "my-app.example.com", "-n", "kube-system"]
      restartPolicy: Never
```

> [!NOTE]
> Хуки удаления запускаются только при полном удалении Application, но **не** при prune (даже если ресурсы удаляются). Если PostDelete-хук завис — Application CR остаётся с condition `DeletionError`; исправьте хук в Git или удалите ресурс хука вручную.

### Сценарий 5: Длительные хуки и таймауты

Ограничение времени выполнения хука — на двух уровнях:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: long-migration
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 3600   # ограничение на уровне Job (Kubernetes)
  template:
    spec:
      containers:
      - name: migrate
        image: migrations-tool:v2.4
        command: ["./migrate.sh"]
        env:
        - name: TIMEOUT
          value: "3600"
      restartPolicy: Never
```

```bash
# Ограничение на уровне операции (CLI); по умолчанию 0 = без таймаута
argocd app sync my-app --timeout 3600
```

Таймаут, после которого контроллер прерывает всю синхронизацию, задаётся на стороне контроллера (см. [Тюнинг таймаутов](#тюнинг-таймаутов)). Если хук «завис», поможет `activeDeadlineSeconds` + `backoffLimit`, а для принудительной остановки операции — `argocd app terminate-op my-app`.

### Сценарий 6: Sync Waves с ApplicationSet

Sync Waves работают внутри каждого приложения, генерируемого ApplicationSet, а RollingSync управляет порядком самих приложений:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: my-app-set
  namespace: argocd
spec:
  generators:
  - clusters: {}
  strategy:
    type: RollingSync
    rollingSync:
      steps:
      - matchExpressions:
          - key: environment
            operator: In
            values: [canary]
        maxUpdate: 1
      - matchExpressions:
          - key: environment
            operator: In
            values: [production]
        maxUpdate: 10%
  template:
    metadata:
      name: '{{name}}-app'
    spec:
      project: default
      source:
        repoURL: https://github.com/my-org/manifests.git
        targetRevision: HEAD
        path: app
      destination:
        server: '{{server}}'
        namespace: production
```

При этом в манифестах приложения (каталог `app`) ресурсы аннотируются `argocd.argoproj.io/sync-wave` как обычно. Подробнее о RollingSync — в [Progressive Sync](./progressive_sync.md), о ApplicationSet — в [Argo CD ApplicationSets](../../argocd_applicationsets.md).

### Сценарий 7: Hooks и Sync Windows

Взаимодействие хуков с окнами синхронизации. `syncOverrun` доступен с v3.5+ и должен быть включён на **всех** подходящих окнах (ALL-семантика):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production-project
  namespace: argocd
spec:
  syncWindows:
  - kind: allow
    schedule: '0 9-17 * * 1-5'
    duration: 8h
    applications:
    - '*'
    manualSync: true
    syncOverrun: true    # v3.5+: запущенный синк завершится после закрытия окна
  - kind: deny
    schedule: '0 0 * * 0,6'
    duration: 24h
    applications:
    - '*'
  syncWindowOptions: {}
```

**Поведение:**

- Окно проверяется при старте операции (до PreSync-хуков) и на каждом проходе контроллера во время операции.
- PreSync-хук, начатый во время allow-окна, не прерывается при закрытии окна: без `syncOverrun` операция **приостанавливается** (`Sync operation blocked by sync window`) и возобновляется при открытии окна; с `syncOverrun: true` — продолжается до конца.
- Новые синхронизации при закрытом окне блокируются (кроме ручных, если `manualSync: true`) независимо от `syncOverrun`.

### Сценарий 8: Хуки для мультикластерных миграций

Хук-Job выполняется **в целевом кластере** (он создаётся контроллером в namespace приложения этого кластера). Для передачи имени приложения в Job используйте метку отслеживания Argo CD (`app.kubernetes.io/instance` по умолчанию), которую контроллер inject-ит на все управляемые ресурсы, включая хуки:

```yaml
# PreSync-хук для миграции в каждом кластере
apiVersion: batch/v1
kind: Job
metadata:
  name: cluster-migrate
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
    argocd.argoproj.io/sync-wave: "-1"
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: migrations-tool:v2.4
        command: ["./migrate.sh"]
        env:
        - name: APP_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['app.kubernetes.io/instance']
      restartPolicy: Never
---
# PostSync-хук для проверки после миграции
apiVersion: batch/v1
kind: Job
metadata:
  name: cluster-verify
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
    argocd.argoproj.io/sync-wave: "1"
spec:
  template:
    spec:
      containers:
      - name: verify
        image: curlimages/curl:latest
        command: ["curl", "-f", "http://my-app:8080/health"]
      restartPolicy: Never
```

> [!NOTE]
> ApplicationSet **не добавляет** меток порождённым приложениям и их ресурсам (только через `preservedLabels`/`globalPreservedLabels`), поэтому рассчитывать на метку `argocd.argoproj.io/cluster` нельзя — её нужно явно задавать в `template.metadata.labels` ApplicationSet, если она требуется.

### Сценарий 9: Skip-хук для admission webhook (разбор из документации)

Обновление ingress-nginx, управляемого через Helm+Argo CD, иногда зависает на хуке `ingress-nginx-admission-create` (синк ждёт completion хука, который не может завершиться, пока webhook не заработал). Решение из официальной документации — исключить ресурс webhook из синхронизации через Skip:

```yaml
# Helm values для ingress-nginx
ingress-nginx:
  controller:
    admissionWebhooks:
      annotations:
        argocd.argoproj.io/hook: Skip
```

Симптом зависания: операция в фазе `Running` с сообщением `waiting for completion of hook batch/Job/ingress-nginx-admission-create`.

### Сценарий 10: Установка оператора и Custom Resources в одном приложении (проблема «Курицы и яйца»)

**Контекст:** типовая задача при установке Prometheus Operator, Cert-Manager или CloudNativePG в Kubernetes. Манифест CustomResourceDefinition (CRD) и манифест использующего его кастомного ресурса (например, `Certificate` или `PrometheusRule`) находятся в одном репозитории или Helm-чарте.

**Проблема:**
1. **Сбой Dry-Run:** перед началом применения Argo CD выполняет пре-валидацию схемы в режиме dry-run. Если CRD еще не установлена в кластере, `kube-apiserver` возвращает ошибку `no matches for kind "Certificate" in version "cert-manager.io/v1"`, и синхронизация аварийно прерывается еще до применения манифестов.
2. **Порядок применения:** если CRD и CR находятся в одной волне, API-сервер отклонит создание CR до завершения регистрации CRD.

**Решение:**
1. Разделение по волнам через аннотацию `argocd.argoproj.io/sync-wave`:
   - CRD и Namespace: волна `"-1"` (или `"-2"`).
   - Deployment/StatefulSet оператора: волна `"0"`.
   - Экземпляры Custom Resources (`Certificate`, `Issuer`): волна `"1"`.
2. Обязательная sync option `SkipDryRunOnMissingResource=true` в манифесте `Application`. Она инструктирует контроллер пропустить dry-run валидацию для тех типов, чьи схемы CRD еще отсутствуют в API-сервере на момент старта синка.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cert-manager-bundle
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://gitlab.internal.company/gitops/platform.git
    targetRevision: main
    path: infrastructure/cert-manager
  destination:
    server: https://kubernetes.default.svc
    namespace: cert-manager
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
    # КРИТИЧЕСКИ ВАЖНО: пропустить валидацию отсутствующих CRD на этапе Dry Run
    - SkipDryRunOnMissingResource=true
    # Рекомендуется для операторов с крупными CRD
    - ServerSideApply=true
```

**Пример разметки манифестов по волнам:**
```yaml
# infrastructure/cert-manager/crd-certificates.yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: certificates.cert-manager.io
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
# ...

---
# infrastructure/cert-manager/operator-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cert-manager-controller
  annotations:
    argocd.argoproj.io/sync-wave: "0"
# ...

---
# infrastructure/cert-manager/production-issuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca-issuer
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  ca:
    secretName: internal-root-ca-secret
```

> [!NOTE]
> В редких случаях после создания CRD в волне `"-1"` discovery-клиент контроллера приложений `argocd-application-controller` может кратковременно не видеть новый API-ресурс из-за кэширования схем. `ARGOCD_SYNC_WAVE_DELAY` (по умолчанию 2с) или кастомный Health Check на CRD гарантируют, что схема успеет зарегистрироваться в K8s API до старта волны `"1"`.

## Технический справочник

### Полная таблица аннотаций

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `argocd.argoproj.io/sync-wave` | Определяет волну (порядок) применения ресурса. Целое число; по умолчанию `0`. | `"10"`, `"-5"`, `"0"` |
| `argocd.argoproj.io/hook` | Определяет фазу жизненного цикла для хука. Допустим список фаз через запятую. | `PreSync`, `PostSync`, `SyncFail`, `PreDelete`, `PostDelete` |
| `argocd.argoproj.io/hook-delete-policy` | Условия автоматической очистки хука. Список через запятую (с v2.10); по умолчанию — `BeforeHookCreation`. | `BeforeHookCreation,HookSucceeded` |
| `helm.sh/hook-weight` | Аннотация **Helm** (не Argo CD): вес Helm-хука; используется как fallback для волны, если `sync-wave` задана нечисловым значением. | `"1"`, `"-5"` |
| `argocd.argoproj.io/ignore-restart-policy` | Оценивать Pod с `restartPolicy: Never/OnFailure` как долгоживущий (влияет только на оценку здоровья; **не действует** на Pods-хуки). | `"true"` |
| `argocd.argoproj.io/ignore-healthcheck` | Исключить ресурс из оценки здоровья приложения. | `"true"` |

Аннотация `argocd.argoproj.io/hook-weight` **не существует** — порядок хуков внутри фазы определяется волной (`sync-wave`), Kind и именем, а не отдельным «весом хука».

### Тюнинг таймаутов

Таймауты хуков и синхронизации настраиваются **на стороне контроллера** (флаги/переменные окружения `argocd-application-controller`, **не** в `argocd-cm`):

```yaml
# argocd-application-controller Deployment (manifests/base/application-controller-deployment)
env:
# Таймаут, после которого контроллер прерывает всю операцию синхронизации.
# 0 (default) = без таймаута.
- name: ARGOCD_APPLICATION_CONTROLLER_SYNC_TIMEOUT
  value: "3600"
# Таймаут RPC-вызовов к repo-server (default 60)
- name: ARGOCD_APPLICATION_CONTROLLER_REPO_SERVER_TIMEOUT_SECONDS
  value: "60"
# Период сверки (default 120) и jitter (default 60)
- name: ARGOCD_RECONCILIATION_TIMEOUT
  value: "120"
- name: ARGOCD_RECONCILIATION_JITTER
  value: "60"
```

Эквивалентные флаги CLI: `--sync-timeout`, `--repo-server-timeout-seconds`, `--app-resync`, `--app-resync-jitter`. В `argocd-cm` период сверки задаётся ключами `timeout.reconciliation` (120s) и `timeout.reconciliation.jitter` (60s).

Для хуков-Job ограничение времени — на уровне Kubernetes (`activeDeadlineSeconds`) и CLI (`argocd app sync --timeout <сек>`). Самоограничения self-heal: `--self-heal-timeout-seconds` (0 = отключено).

> [!NOTE]
> Параметров `controller.process.timeout.seconds`, `controller.kubectl.timeout.seconds` и `controller.repo.server.timeout.seconds` **не существует** ни в `argocd-cm`, ни среди флагов контроллера. Единственный «kubectl-таймаут» контроллера — `--kubectl-parallelism-limit` (default 20, ограничивает параллельизм, а не таймаут).

### CLI-команды

```bash
# Состояние приложения, дерево ресурсов, состояние операции
# (прогресс хука виден в сообщении операции, например:
#  "waiting for completion of hook batch/Job/db-migrate")
argocd app get my-app

# То же в формате json/yaml/wide/tree
argocd app get my-app -o yaml

# Обычный синк с выполнением хуков (PreSync -> ресурсы -> PostSync)
argocd app sync my-app

# Синк без хуков (хук-ресурсы не применяются и не выполняются)
argocd app sync my-app --strategy apply

# Синк с ограничением времени операции (0 = без таймаута, default)
argocd app sync my-app --timeout 600

# Остановка зависшей операции (например, зависшего хука)
argocd app terminate-op my-app

# Откат к предыдущей версии (или к конкретной History ID)
argocd app rollback my-app
argocd app rollback my-app 3

# Hook-Job приложения: они несут метку отслеживания Argo CD
# (app.kubernetes.io/instance=<app-name> по умолчанию)
kubectl get jobs -n <namespace> -l app.kubernetes.io/instance=my-app

# Логи конкретного hook-Job
kubectl logs -n <namespace> -l job-name=db-migrate

# События приложения
kubectl get events -n <namespace> --field-selector involvedObject.name=my-app
```

## Диагностика и мониторинг

### Просмотр состояния хуков и волн

```bash
# Состояние приложения и дерево ресурсов (фазы хуков, сообщения операции)
argocd app get my-app

# Детали в машинно-читаемом виде (включая status.operationState с результатами
# синхронизации: hookType, hookPhase для каждого ресурса)
argocd app get my-app -o yaml

# Hook-Jobs приложения (по метке отслеживания)
kubectl get jobs -n <namespace> -l app.kubernetes.io/instance=my-app

# Pods hook-Job
kubectl get pods -n <namespace> -l app.kubernetes.io/instance=my-app

# Волна конкретного ресурса
kubectl get deployment my-app -n <namespace> -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/sync-wave}'
```

### Просмотр логов

```bash
# Логи контроллера (хуки и волны)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep -i "hook\|wave"

# Логи конкретного hook-Job
kubectl logs -n <namespace> -l job-name=db-migrate

# Логи контроллера с фильтрацией по Application
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep my-app
```

### Prometheus метрики

| Метрика | Описание |
| :--- | :--- |
| `argocd_app_info` | Информация о приложении (gauge); labels `sync_status`, `health_status`, `autosync_enabled`, `repo`, `dest_server`, `dest_namespace`, `operation`, `phase` + `namespace`, `name`, `project`. |
| `argocd_app_sync_total` | Количество завершённых синхронизаций (counter); labels `phase` (`Succeeded`/`Failed`/`Error`), `dry_run`, `dest_server` + стандартные. |
| `argocd_app_sync_duration_seconds_total` | Суммарная длительность синхронизаций, секунды (counter); labels `dest_server` + стандартные. |
| `argocd_app_reconcile` | Гистограмма длительности сверки, секунды (buckets 0.25, 0.5, 1, 2, 4, 8, 16); labels `namespace`, `dest_server`. |
| `argocd_app_orphaned_resources_count` | Количество orphaned-ресурсов приложения (gauge). |
| `argocd_kubectl_exec_total` / `argocd_kubectl_exec_pending` | Количество выполненных / ожидающих kubectl-операций. |
| `argocd_app_sync_window` / `argocd_app_sync_blocked` / `argocd_app_sync_window_error` | Метрики Sync Windows (v3.5+; включаются флагом контроллера `--metrics-sync-windows`). |

**Пример PromQL-запросов для диагностики хуков и волн:**

```promql
# Приложения в состоянии Degraded (возможно, заблокированная волна)
argocd_app_info{health_status="Degraded"}

# Ошибочные синхронизации (в т.ч. из-за упавших хуков)
rate(argocd_app_sync_total{phase="Error"}[5m]) > 0

# Частота синхронизаций (деплой-менторика: успешные за 24ч)
sum(increase(argocd_app_sync_total{phase="Succeeded"}[24h]))

# Доля неудачных синхронизаций (Change Failure Rate)
sum(rate(argocd_app_sync_total{phase="Failed"}[1h])) / sum(rate(argocd_app_sync_total[1h]))

# p95 длительности сверки
histogram_quantile(0.95, sum by (le) (rate(argocd_app_reconcile_bucket[5m])))
```

### Пошаговый алгоритм диагностики

1. **Проверьте состояние операции:** `argocd app get my-app` — статус `Progressing` с сообщением `waiting for completion of hook ...` означает, что выполняется хук; `Degraded` — проблема со здоровьем ресурса (волна заблокирована).
2. **Просмотрите лог контроллера:** `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep -i "hook\|wave"` — ошибки фаз и волн.
3. **Проверьте Job хука:** `kubectl get jobs -n <namespace> -l app.kubernetes.io/instance=my-app` — статус Completion/Failed и `backoffLimit`.
4. **Просмотрите логи Pod хука:** `kubectl logs -n <namespace> -l job-name=<job-name>`.
5. **Проверьте политику удаления:** если Job остаётся после синхронизации — проверьте `hook-delete-policy` (по умолчанию `BeforeHookCreation` — удаляет старый Job только перед созданием нового).
6. **Исправьте проблему:** конфигурация в Git, откат (`argocd app rollback my-app`) или остановка зависшей операции (`argocd app terminate-op my-app`).

## Лучшие практики

### Настройка для Production

1. **Используйте `BeforeHookCreation` для именованных хуков:** гарантирует отсутствие конфликтов имён Job при повторных синхронизациях; для безымянных хуков — `generateName`.
2. **Используйте `HookSucceeded` для успешных запусков:** очистка Job после успешного завершения (список политик через запятую — с v2.10).
3. **Ограничивайте время хуков:** `activeDeadlineSeconds` и `backoffLimit` на Job; `--timeout` на операции; `--sync-timeout` на контроллере (по умолчанию 0 = без ограничения).
4. **Делайте хуки идемпотентными:** они выполняются при каждой синхронизации (self-heal, ручной синк, независимые изменения), а не только при изменении самих хуков.
5. **Настройте Health Checks для операторов:** Lua-скрипты в `argocd-cm` для CRD, иначе волны не смогут дождаться готовности (ресурс будет в `Progressing`).
6. **Используйте разреженную нумерацию волн** (`-10`, `0`, `10`): позволяет вставлять промежуточные ресурсы без правки всего набора манифестов.
7. **Помните про задержку между волнами** (2с по умолчанию, `ARGOCD_SYNC_WAVE_DELAY`): она влияет на общее время деплоя при большом числе волн.

### Безопасность

- **Настройте RBAC:** ограничьте доступ к ресурсам хуков (Job, CronJob) и к `argocd app sync`/`rollback` только авторизованным пользователям; откат требует отдельного разрешения при `server.rbac.rollback.enforce.enable: "true"`.
- **Мониторинг:** алерты на `argocd_app_sync_total{phase="Error"}` и `health_status="Degraded"` отслеживают как сбои хуков, так и заблокированные волны.

## Ограничения и edge cases

### Ограничения

1. **Health Gating между волнами:** следующая волна применяется только когда текущая полностью `Healthy`. Если ресурс не становится `Healthy` — прогресс останавливается навсегда (включая все последующие волны и PostSync-хуки).
2. **PreSync-хуки выполняются до основных ресурсов:** при сбябре хука синхронизация прерывается, основные ресурсы не применяются, PostSync не запускается.
3. **PostSync-хуки выполняются после `Healthy` всех ресурсов:** если хотя бы один ресурс не становится `Healthy`, PostSync-хук не выполняется.
4. **PreDelete/PostDelete:** PreDelete требует Argo CD v3.3+, PostDelete — v2.10+. Оба запускаются только при полном удалении Application, не при обычной синхронизации (даже с prune).
5. **Хуки не выполняются при селективной синхронизации** и при `--strategy apply`.
6. **Retry применяется к операции целиком** (включая хуки) и не ограничивает время выполнения; пока операция не завершена, retry не запускается.
7. **Sync Waves работают внутри приложения**, Progressive Sync — между приложениями; комбинируются, но не заменяют друг друга.
8. **Порядок внутри фазы** определяется только волной, Kind и именем — отдельного «веса хука» (`hook-weight`) в Argo CD нет.

### Edge Cases

1. **Конфликт имён Job:** если именованный PreSync-хук создаёт Job, который уже существует, синхронизация завершится ошибкой. Используйте `BeforeHookCreation` или `generateName`.
2. **Долгий PreSync-хук:** если хук выполняется дольше таймаута операции (`--sync-timeout`, по умолчанию без ограничения), операция прервётся, но сам хук продолжит работу в кластере. Ограничьте `activeDeadlineSeconds`.
3. **PreDelete-хук не завершается:** удаление ресурсов не произойдёт — Application застрянет в deleting с condition `DeletionError`. Исправьте хук в Git (контроллер повторит на следующей сверке) или удалите ресурс хука вручную.
4. **PostDelete-хук не завершается:** Application уже удалён из кластера, но CR остаётся с condition `DeletionError`; хук не собирается мусором автоматически. Исправление — через Git или ручное удаление ресурса хука.
5. **Кастомный Health Check не возвращает `Healthy`:** волна блокируется навсегда. Проверьте Lua-скрипт и поле `status` CRD.
6. **Синхронизация во время закрытия окна:** окно проверяется при старте и на каждом проходе контроллера; без `syncOverrun` (v3.5+) операция приостанавливается на границе окна, с `syncOverrun` — завершается.
7. **Удаление ApplicationSet во время прогресса:** если ApplicationSet удалён во время выполняющейся синхронизации, операция завершится, но новые синхронизации будут невозможны.
8. **Хук читает Secret из того же Application:** PreSync-хук применяется до Secret/ConfigMap приложения — при ротации пароля хук получит старое значение или упадёт. Держите учётные данные хуков вне Application или вынесите Secret в хук с меньшей волной.
9. **Job-хук завершился с exit 0, но внешнее состояние не изменилось:** Argo CD оценивает успех фазы по ресурсу-хуку, а не по внешнему состоянию. Для гейтинга на реальном состоянии используйте CR с контроллером и custom health check.
10. **ttlSecondsAfterFinished на Job-хуке:** Kubernetes удалит Job до того, как Argo CD прочитает его результат — синк может зависнуть в ожидании хука. Используйте `hook-delete-policy`.

## Дополнительная информация

### Важные нюансы

- **Health Gating:** волна считается применённой только когда все её ресурсы `Healthy`; ресурсы без health-проверки (ConfigMap, Secret, ServiceAccount) — сразу.
- **Prune реверсирует волны:** при удалении лишних ресурсов сначала удаляются ресурсы из более высоких волн; сбой в волне блокирует удаление более низких.
- **Задержка между волнами:** 2 секунды по умолчанию (`ARGOCD_SYNC_WAVE_DELAY`), чтобы контроллеры успели отреагировать на применённый spec.
- **Хуки и Helm:** при маппинге Helm-хуков на Argo CD-хуки оценка политик удаления следует фазам Argo CD, а не per-event lifecycle Helm; `helm.sh/hook-weight` используется только как fallback для волны.

### См. также

- **[Синхронизация Argo CD: Обзор](../../synchronization.md)** — механизмы и фазы.
- **[Автоматическая синхронизация](./auto_sync.md)** — использование волн в авто-деплое и retry.
- **[Ручная синхронизация](./manual_sync.md)** — селективный деплой и аудит изменений.
- **[Окна синхронизации](./sync_windows.md)** — политики запрета деплоя и `syncOverrun`.
- **[Прогрессивная синхронизация](./progressive_sync.md)** — поэтапная раскатка между приложениями.
- **[Игнорирование различий](../ignore_differences.md)** — настройка jqPath и managedFieldsManagers.
- **[Argo CD ApplicationSets](../../argocd_applicationsets.md)** — генераторы и шаблоны.
- **[Диагностика Argo CD](../../argocd_troubleshooting_and_monitoring.md)** — поиск причин зависания хуков.

### Ссылки

- [Argo CD Documentation: Sync Phases and Waves](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)
- [Argo CD Documentation: Resource Hooks](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_hooks/)
- [Argo CD Health Assessment](https://argo-cd.readthedocs.io/en/stable/operator-manual/health/)
- [argocd-application-controller Command Reference](https://argo-cd.readthedocs.io/en/stable/operator-manual/server-commands/argocd-application-controller/)
