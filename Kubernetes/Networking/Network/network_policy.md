# NetworkPolicy: Навигатор

**NetworkPolicy** — ресурс Kubernetes для декларативного управления правилами доступа к сети (L3/L4) между подами. Работает только при поддержке CNI-плагином (Calico, Cilium, Weave Net).

Файл выполняет роль навигатора по документации NetworkPolicy с ссылками на специализированные разделы.

---

## Определения

**NetworkPolicy** — встроенный файрвол Kubernetes, позволяющий разрешать или запрещать трафик на уровне IP-адресов и портов. Функционирует как опция безопасности "opt-in": без политик весь трафик разрешён, при применении хотя бы одной политики включается режим "запрещено по умолчанию".

* *Подробные определения и базовые концепции: [NetworkPolicy: определения](./NetworkPolicy/definitions.md)*

### Терминология

| Термин | Описание |
|--------|----------|
| **Target** | Поды, к которым применяется политика (`spec.podSelector`) |
| **Source** | Источник трафика (`spec.ingress.from`) |
| **Destination** | Назначение трафика (`spec.egress.to`) |
| **Default Deny** | Режим запрета всего трафика при наличии хотя бы одной политики |
| **Default Allow** | Режим разрешения всего трафика при отсутствии политик |

* *Логика правил и операторы: [rule_logic.md](./NetworkPolicy/rule_logic.md)*

---

## Основные концепции

### Принцип работы

* **Default Allow**: Без политик весь трафик разрешён (плоская сетевая модель Kubernetes)
* **Default Deny**: При применении хотя бы одной политики весь трафик запрещается, кроме явно разрешённого
* **Направления**: `Ingress` (входящий), `Egress` (исходящий) или оба (`policyTypes`)

* *Структура NetworkPolicy и примеры YAML: [definitions.md](./NetworkPolicy/definitions.md#структура-networkpolicy)*

### Требования к CNI

| Плагин | Поддержка | Особенности |
|--------|-----------|-------------|
| **Calico** | ✅ Полная | Расширения: HostEndpoint, GlobalNetworkPolicy, логирование |
| **Cilium** | ✅ Полная | Реализация через eBPF, высокая производительность |
| **Weave Net** | ✅ Базовая | Стандартная поддержка NetworkPolicy |
| **Flannel** | ❌ Нет | Не поддерживает NetworkPolicy в стандартной конфигурации |

* *Детали реализации в CNI: [cni_implementation.md](./NetworkPolicy/cni_implementation.md)*

### Логика правил

* **Логическое "ИЛИ"**: Элементы в списках `ingress`, `egress`, `from`, `to` объединяются по "ИЛИ"
* **Логическое "И"**: Поля внутри одного элемента (`podSelector`, `namespaceSelector`, `ports`) объединяются по "И"

* *Примеры комбинаций правил: [rule_logic.md](./NetworkPolicy/rule_logic.md)*

### Типовые политики

**Deny-all (запрет всего входящего трафика):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
spec:
  podSelector: {}
  policyTypes:
  - Ingress
```

**Allow-all (разрешение всего трафика):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-all
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - {}
```

* *Подробнее о типовых политиках: [definitions.md](./NetworkPolicy/definitions.md#типовые-политики-allow-all-и-deny-all)*

---

## Практические сценарии

| Сценарий | Описание | SSoT |
|----------|----------|------|
| **Default Deny** | Полная изоляция namespace | [practical_scenarios.md](./NetworkPolicy/practical_scenarios.md#шаг-1-полная-изоляция-неймспейса-default-deny) |
| **Allow by Namespace** | Разрешение трафика из определённых namespace | [practical_scenarios.md](./NetworkPolicy/practical_scenarios.md#шаг-2-разрешение-трафика-от-конкретного-приложения) |
| **Allow by IP** | Разрешение трафика из внешних IP-диапазонов | [definitions.md](./NetworkPolicy/definitions.md#источники-from-и-назначения-to) |
| **DNS Access** | Разрешение доступа к DNS для работы подов | [practical_scenarios.md](./NetworkPolicy/practical_scenarios.md#шаг-5-разрешение-трафика-к-dns) |
| **Egress-изоляция** | Контроль исходящего трафика | [practical_scenarios.md](./NetworkPolicy/practical_scenarios.md#шаг-4-egress-политика-и-проблема-с-dns) |

* *Пошаговые сценарии с примерами YAML: [practical_scenarios.md](./NetworkPolicy/practical_scenarios.md)*
* *Лучшие практики внедрения: [best_practices.md](./NetworkPolicy/best_practices.md)*

### Диагностика

```bash
# Проверка применённых политик
kubectl get networkpolicy -n <namespace>

# Детальная информация о политике
kubectl describe networkpolicy <name> -n <namespace>

# Тестирование连通ности
kubectl run test --rm -it --image=busybox -- nslookup <service>

# Удаление всех политик в namespace
kubectl delete networkpolicy --all -n <namespace>
```

---

## Дополнительные сведения

### Важные нюансы

**Трафик внутри пода:** NetworkPolicy не ограничивает трафик между контейнерами внутри одного пода — они общаются через `localhost`.

**Двусторонний трафик:** Для подключения от пода А к поду Б необходимо разрешить трафик и в `egress`-политике пода А, и в `ingress`-политике пода Б.

**Проблема NAT:** При использовании `NodePort` или `LoadBalancer` без `externalTrafficPolicy: Local` исходный IP клиента подменяется на IP ноды. В `ipBlock` нужно указывать подсеть нод.

* *Подробнее о нюансах: [definitions.md](./NetworkPolicy/definitions.md#важные-нюансы-реализации)*

### Визуализация

Для проверки и отладки политик рекомендуется использовать визуализаторы, например [Orca Turfin](https://orca-tufin.com/), которые преобразуют YAML в графическое представление правил.

### Сетевая модель Kubernetes

NetworkPolicy работает в контексте общей сетевой модели Kubernetes, основанной на принципе IP-per-Pod.

* *Обзор сетевой модели: [network_overview.md](./network_overview.md)*
* *CNI и kube-proxy: [cni_kube_proxy_roles.md](./cni_kube_proxy_roles.md)*

### Calico-specific расширения

Calico расширяет стандартные NetworkPolicy дополнительными возможностями:

* **HostEndpoint**: Политики для узлов кластера
* **GlobalNetworkPolicy**: Глобальные политики на уровне кластера
* **Логирование**: Логирование заблокированного трафика

* *Calico HostEndpoint и GlobalNetworkPolicy: [../../Security/network_policies/Calico/index.md](../../Security/network_policies/Calico/index.md)*
