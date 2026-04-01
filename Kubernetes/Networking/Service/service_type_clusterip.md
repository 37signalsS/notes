# ClusterIP

## Определения

**ClusterIP** — тип Service, предоставляющий внутренний IP-адрес, доступный **только внутри кластера**. Тип **по умолчанию** для всех сервисов Kubernetes.

Создаёт стабильную виртуальную точку доступа к группе Pod, позволяя внутренним компонентам приложения взаимодействовать без привязки к конкретным IP-адресам подов.

## Основные концепции

### Принцип работы

При создании Service типа ClusterIP:

1. Kubernetes назначает виртуальный IP из диапазона `ClusterIP` (по умолчанию 10.96.0.0/12)
2. Создаётся DNS-запись вида `service.namespace.svc.cluster.local`
3. `kube-proxy` настраивает правила маршрутизации (`iptables` или `IPVS`) для перенаправления трафика с виртуального IP на реальные Pod

### Ключевые правила

| Правило | Описание |
| :--- | :--- |
| **Селектор меток** | Service выбирает Pod через `selector`, должен точно совпадать с метками подов |
| **Namespace** | Pod и Service должны быть в одном namespace для прямого взаимодействия (между namespace используется FQDN) |

### Особенности

| Особенность | Описание |
| :--- | :--- |
| **DNS-имя** | `service.namespace.svc.cluster.local` (доступно внутри кластера) |
| **Балансировка** | Распределение через `kube-proxy` (режимы `iptables` или `IPVS`) |
| **Session Affinity** | Поддержка `sessionAffinity: ClientIP` для привязки сессии к конкретному поду |

#### Session Affinity

По умолчанию балансировка работает по алгоритму round-robin. Для привязки клиента к одному поду:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: sticky-service
spec:
  selector:
    app: my-app
  type: ClusterIP
  sessionAffinity: ClientIP  # Привязка сессии по IP клиента
  ports:
    - name: http
      port: 80
      targetPort: 8080
```

**Применение:** Stateful-приложения, кэширование сессий, WebSocket-соединения.

## Практические сценарии

### Пример манифеста

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  selector:
    app: my-app
  type: ClusterIP  # Можно не указывать — значение по умолчанию
  ports:
    - name: http
      protocol: TCP
      port: 80         # Порт сервиса внутри кластера
      targetPort: 8080 # Порт на Pod
```

### Распространённые use-case

| Сценарий | Описание |
| :--- | :--- |
| **Backend-to-Database** | Веб-приложение обращается к PostgreSQL/MySQL через ClusterIP |
| **Microservices communication** | Сервисы внутри приложения взаимодействуют друг с другом |
| **Internal APIs** | API, не предназначенные для внешнего доступа |

### Доступ для отладки

Для временного доступа к ClusterIP извне кластера используйте `kubectl port-forward`:

```bash
# Проброс локального порта 8080 на порт 80 сервиса
kubectl port-forward -n <namespace> service/<service-name> 8080:80
```

**Важно:** Метод предназначен только для отладки и разработки, **не для production**.

> **Полный пример:** Пошаговое создание ClusterIP и преобразование в NodePort см. в [Практическом сценарии](./service_practical_scenarios.md).

## Дополнительная информация

### Сравнение с другими типами

ClusterIP — базовый тип, используемый как фундамент для:

- **[NodePort](./service_type_nodeport.md)** — добавляет публикацию через порт узла (порт 30000-32767)
- **[LoadBalancer](./service_type_loadbalancer.md)** — добавляет облачный балансировщик с публичным IP

Для полного сравнения всех типов см. [Сводку по типам сервисов](./service_types_summary.md).

### Ограничения

| Ограничение | Описание |
| :--- | :--- |
| **Нет внешнего доступа** | Недоступен извне кластера без port-forward или прокси |
| **Только L4** | Балансировка на транспортном уровне (TCP/UDP), без понимания HTTP |
| **Один IP** | Все сервисы используют один виртуальный IP, доступ через DNS |
