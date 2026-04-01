# ExternalIPs

## Определения

**ExternalIPs** — поле в спецификации `Service`, позволяющее привязать сервис к одному или нескольким статическим внешним IP-адресам, которые вы контролируете. Трафик, поступающий на эти IP-адреса, маршрутизируется `kube-proxy` на поды, обслуживаемые данным сервисом.

Это **не тип сервиса**, а **свойство**, применимое к любым типам: `ClusterIP`, `NodePort`, `LoadBalancer`.

> **⚠️ Важно: депрекация в v1.36**
>
> Поле `externalIPs` **депрецируется в Kubernetes v1.36** (ноябрь 2025). Причина — уязвимость безопасности [CVE-2020-8554](https://github.com/kubernetes/kubernetes/issues/91507) (атака Man-in-the-Middle).
>
> **KEP:** [5707-deprecate-service-externalips](https://github.com/kubernetes/enhancements/blob/master/keps/sig-network/5707-deprecate-service-externalips/README.md)
>
> **Рекомендация:** Планируйте миграцию на альтернативы (LoadBalancer, Ingress, MetalLB).

## Основные концепции

### Принцип работы

При указании IP-адресов в поле `externalIPs`, `kube-proxy` на каждом узле создает правила (`iptables` или `IPVS`), которые перехватывают трафик, предназначенный для внешних IP, и перенаправляют его на `ClusterIP` сервиса.

**Ключевые требования:**

- Внешние IP должны **маршрутизироваться на узлы кластера**
- Настройка маршрутизации — **ответственность администратора**, Kubernetes не управляет выделением IP
- Требуется предварительная настройка сетевой инфраструктуры

### Ключевые отличия

| Характеристика | ExternalIPs | NodePort | LoadBalancer |
| :--- | :--- | :--- | :--- |
| **Доступ** | Конкретный внешний IP | Порт на всех узлах | Публичный IP от облака |
| **Управление IP** | Вы предоставляете | Не требуется | Облачный провайдер |
| **Сложность** | Высокая (настройка сети) | Низкая | Низкая (в облаке) |
| **Статус** | Депрецируется v1.36 | Стабилен | Стабилен |

## Практические сценарии

### Пример манифеста

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app-service
spec:
  selector:
    app: my-app
  ports:
    - name: http
      protocol: TCP
      port: 80
      targetPort: 8080
  # Привязываем сервис к внешнему IP, который вы контролируете
  externalIPs:
    - 203.0.113.10
```

Трафик на `203.0.113.10:80` направляется на порт `8080` подов с меткой `app: my-app`.

### Распространённые use-case

- **Интеграция с существующей инфраструктурой:** Использование выделенных IP-адресов с настроенной маршрутизацией до узлов кластера.
- **Отказоустойчивые IP (VIP):** В паре с VRRP/Keepalived, где виртуальный IP мигрирует между машинами.
- **Bare-metal кластеры:** Альтернатива LoadBalancer при отсутствии облачного провайдера.

### Альтернативы (рекомендуемые)

| Сценарий | Альтернатива |
| :--- | :--- |
| Bare-metal production | [MetalLB](../metallb.md) |
| HTTP/HTTPS приложения | [Ingress](../Ingress/overview.md) |
| Облачная среда | [LoadBalancer](./service_type_loadbalancer.md) |
| Разработка/тестирование | [NodePort](./service_type_nodeport.md) + `kubectl port-forward` |

## Дополнительная информация

### Вопросы безопасности

**CVE-2020-8554:** Уязвимость позволяет поду с привилегированным доступом перехватывать трафик, предназначенный для других приложений, через манипуляцию с `externalIPs` или `LoadBalancer`.

**Меры защиты:**

- Ограничение доступа к созданию/редактированию Service через [RBAC](../../Security/rbac/rbac_overview.md)
- Использование [NetworkPolicy](../Network/NetworkPolicy/definitions.md) для изоляции трафика
- Валидация через [Kyverno](../../Security/kyverno/concepts.md) или [Pod Security Admission](../../Security/pod_security_context.md)
- Отключение функции на уровне кластера (флаг `--feature-gates=ExternalIPs=false`)

### Связанные концепции

- [NodePort](./service_type_nodeport.md) — внешний доступ через порт на узлах
- [LoadBalancer](./service_type_loadbalancer.md) — облачный балансировщик
- [Сводка типов сервисов](./service_types_summary.md) — сравнение всех типов
