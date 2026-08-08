# Продвинутые темы Pod в Kubernetes

## Определения

**Неизменяемые поля (Immutable fields)** — поля спецификации Pod, которые запрещено модифицировать после создания объекта. Изменение таких полей требует удаления и пересоздания Pod.

**Врата готовности (Readiness Gates)** — механизм расширения стандартных проверок готовности Pod. Позволяет внешним контроллерам (например, Ingress или Service Mesh) влиять на статус готовности Pod, добавляя собственные условия (Conditions).

**Врата планирования (Scheduling Gates)** — механизм, позволяющий удерживать Pod в состоянии `Pending` до выполнения внешних условий (например, проверки безопасности или квот), блокируя работу стандартного планировщика.

**Оверхед пода (Pod Overhead)** — фиксированный объем ресурсов (CPU, память), который резервируется для нужд самой среды выполнения (Runtime) и не учитывается в лимитах контейнеров.

---

## Базовые концепции

### Редактирование работающего Pod

Большинство параметров Pod фиксируются при создании. Однако Kubernetes позволяет изменять «на лету» ограниченный набор полей.

**Доступные для редактирования поля:**

| Поле | Описание |
| :--- | :--- |
| `spec.containers[*].image` | Имена и теги образов контейнеров. Вызывает перезапуск контейнера. |
| `spec.initContainers[*].image` | Теги образов для инициализирующих контейнеров. |
| `spec.activeDeadlineSeconds` | Лимит времени жизни Pod (прекращает работу при превышении). |
| `spec.tolerations` | Добавление новых исключений для Taints (только добавление). |
| `spec.terminationGracePeriodSeconds` | (v1.25+) Позволяет изменить время ожидания перед `SIGKILL`. |

**Критически важные неизменяемые поля:**
*   `spec.containers[*].command`, `args`, `env`, `ports`.
*   `spec.volumes` и `volumeMounts`.
*   `spec.nodeName` (после того как Pod запланирован).

### Изоляция и RuntimeClass

Механизм `RuntimeClass` позволяет выбирать разные рантаймы для конкретных подов в зависимости от требований к безопасности или производительности.

*   **Стандартный рантайм:** `runc` (обычные контейнеры).
*   **Изолированные рантаймы:** `gVisor` (runsc) или `Kata Containers` (виртуализация на уровне ядра).
*   **Использование:** Поле `spec.runtimeClassName` ссылается на соответствующий объект `RuntimeClass` в кластере.

### Продвинутая сетевая конфигурация

Kubernetes позволяет тонко настраивать DNS и идентификацию пода внутри сети.

1.  **DNS Config (`dnsConfig`):** Позволяет переопределять `nameservers`, `searches` и параметры `options` (например, `ndots:5`) для конкретного Pod.
2.  **Hostname и Subdomain:** Пода можно назначить `hostname` и `subdomain`, что создаст FQDN вида `hostname.subdomain.namespace.svc.cluster.local` (требуется Headless Service).
3.  **setHostnameAsFQDN (v1.22+):** Флаг, заставляющий Kubernetes устанавливать полное доменное имя в качестве имени хоста внутри контейнера.

### Врата готовности (Readiness Gates)

По умолчанию Pod считается готовым (`Ready: True`), если все его контейнеры прошли `readinessProbe`. С помощью `readinessGates` можно добавить внешние условия.

**Пример логики:**
1.  Облачный балансировщик (ALB/NLB) должен зарегистрировать IP пода.
2.  Балансировщик сообщает Kubernetes, что регистрация завершена.
3.  Только после этого Pod переходит в `Ready` и начинает принимать трафик через Service.

---

## Практические сценарии

### Пример 1: Настройка DNS и Hostname

Сценарий для кластерных приложений (например, базы данных), требующих стабильных имен внутри сети:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: cluster-node-0
spec:
  hostname: node-0
  subdomain: cluster-internal
  dnsConfig:
    options:
      - name: ndots
        value: "2"
  containers:
  - name: app
    image: busybox
    command: ["sh", "-c", "hostname -f && sleep 3600"]
```

### Пример 2: Использование Readiness Gates

Конфигурация, ожидающая внешнего подтверждения от контроллера `example.com/gate`:

```yaml
apiVersion: v1
kind: Pod
spec:
  readinessGates:
    - conditionType: "example.com/gate"
  containers:
    - name: web
      image: nginx
# Статус пода не станет Ready, пока условие example.com/gate не будет установлено в True
```

### Пример 3: Диагностика через Termination Message

Позволяет сохранить причину падения приложения в статус пода, не заглядывая в логи:

```yaml
spec:
  containers:
  - name: app
    image: busybox
    terminationMessagePath: /dev/termination-log
    terminationMessagePolicy: File
    command: ["sh", "-c", "echo 'Critical Database Error' > /dev/termination-log && exit 1"]
```

---

## Дополнительная информация

**Связанные темы:**

*   [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — детали фаз и условий.
*   [Изменение ресурсов без перезапуска (In-Place Resize)](../../Autoscaling/in_place_pod_resize.md) — динамическое управление CPU/RAM.
*   [Приоритеты и вытеснение подов (PriorityClass)](../../Concepts/priorityclass.md) — управление очередью планирования.
*   [Управление размещением подов (Affinity, TSC)](../../Scheduling/affinity.md) — обеспечение отказоустойчивости.
*   [Taints and Tolerations](../Scheduling/taints_and_tolerations.md) — управление размещением на узлах.
