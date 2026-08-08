# Методы доступа к GitLab в Kubernetes

Руководство по настройке внешнего доступа к веб-интерфейсу и Git-сервисам GitLab при развертывании в кластерах Kubernetes.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Ingress** | Ресурс Kubernetes, управляющий HTTP/HTTPS доступом к сервисам через правила маршрутизации. |
| **Gateway API** | Современный стандарт Kubernetes для управления трафиком, заменяющий Ingress (используется в Helm-чартах GitLab 17.x+ через Envoy). |
| **LoadBalancer** | Тип Service, запрашивающий внешний IP у облачного провайдера или MetalLB. |
| **ExternalDNS** | Инструмент для автоматического создания DNS-записей в облачных провайдерах (Route53, Cloudflare) на основе Ingress/Service. |
| **Cert-Manager** | Контроллер для автоматического выпуска и обновления SSL-сертификатов (Let's Encrypt и др.). |
| **SSH-доступ** | Доступ через порт 22 (или альтернативный) для выполнения операций `git clone/push` по протоколу SSH. |

---

## Основные концепции

### Протоколы и порты

Для полноценной работы GitLab требуется настройка доступа по двум основным протоколам:
1.  **HTTP/HTTPS (Порты 80, 443):** Веб-интерфейс, API, Container Registry, KAS (Kubernetes Agent Server).
2.  **SSH (Порт 22):** Операции с репозиториями. В Kubernetes порт 22 часто занят системным SSH узлов, что требует использования альтернативных портов (например, 2222) или выделенных IP.

### Архитектура трафика

В современных инсталляциях GitLab Helm Chart трафик проходит через следующие уровни:
`Клиент → Внешний Балансировщик (L4) → Ingress/Gateway Controller (L7) → GitLab Webservice (Puma)`.

- **Встроенный Ingress:** По умолчанию чарт устанавливает `ingress-nginx`.
- **Переход на Gateway API:** Начиная с версии чарта 8.0 (GitLab 17.0), введена экспериментальная поддержка Gateway API и Envoy Gateway для повышения производительности и гибкости управления трафиком.

---

## Практические сценарии

### Настройка LoadBalancer в облачной среде

Для автоматического создания балансировщика с нужными параметрами используются аннотации в `values.yaml`.

**Пример для AWS (Network Load Balancer):**

```yaml
nginx-ingress:
  controller:
    service:
      annotations:
        service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
        service.beta.kubernetes.io/aws-load-balancer-backend-protocol: "tcp"
```

### Настройка доступа в Bare-Metal через MetalLB

Если кластер развернут на собственных серверах, используйте MetalLB для реализации типа `LoadBalancer`.

**Пример привязки конкретного IP:**

```bash
# Установка GitLab с выделенным статическим IP из пула MetalLB
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --set nginx-ingress.controller.service.loadBalancerIP=192.168.1.50
```

### Организация SSH-доступа

Существует три способа проброса SSH-трафика:

1.  **Тип Service: LoadBalancer:** Самый простой способ, если есть свободные внешние IP. Создается отдельный L4 балансировщик для порта 22.
2.  **TCP Ingress (Nginx):** Проксирование порта 22 через Ingress-контроллер. Требует добавления порта в `ConfigMap` контроллера.
3.  **Альтернативный порт:** Использование порта 2222, чтобы избежать конфликтов с SSH узлов.

**Настройка альтернативного порта в GitLab:**

```yaml
global:
  shell:
    port: 2222
```

### Автоматизация SSL с Cert-Manager

GitLab чарт может автоматически устанавливать `cert-manager` или использовать существующий.

**Настройка Let's Encrypt:**

```yaml
global:
  ingress:
    configureCertmanager: true
  hosts:
    domain: example.com
certmanager-issuer:
  email: admin@example.com
```

### Настройка ExternalDNS

Для автоматического создания DNS-записей при создании Ingress:

```yaml
nginx-ingress:
  controller:
    publishService:
      enabled: true # Позволяет ExternalDNS видеть внешний IP балансировщика
```

### Доступ к GitLab Pages и Container Registry

Эти компоненты часто требуют выделенных доменов или портов:

1.  **Container Registry:** По умолчанию доступен через тот же Ingress, что и GitLab, но на отдельном домене (например, `registry.example.com`). Требует настройки SSL для работы `docker login`.
2.  **GitLab Pages:** Требует wildcard-записи в DNS (`*.pages.example.com`) и часто выделенного IP-адреса для корректной маршрутизации трафика к подам Pages.

**Пример конфигурации Pages в values.yaml:**

```yaml
global:
  pages:
    enabled: true
    host: pages.example.com
```

---

## Решение проблем

### Состояние Pending у LoadBalancer
- **Причина:** Отсутствие контроллера балансировщика (Cloud Provider или MetalLB).
- **Решение:** Проверьте логи `cloud-controller-manager` или статус `MetalLB`.

### Ошибка 502 / 504 при доступе
- **Причина:** GitLab Webservice (Puma) еще не загрузился или упал.
- **Решение:** Проверьте статус подов (`kubectl get pods -l app=webservice`) и логи Puma.

### Ошибка SSL: "Certificate Signed by Unknown Authority"
- **Причина:** Используются самоподписанные сертификаты.
- **Решение:** Установите `global.hosts.https: false` для тестов или правильно настройте `ClusterIssuer` в cert-manager.

---

## Дополнительная информация

### См. также

- [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)
- [Типы сервисов Kubernetes](../Networking/Service/service_types_summary.md)
- [Архитектура и компоненты GitLab](../../CI-CD/GitLab_CI/Concepts/gitlab_platform_architecture.md)
- [Официальная документация GitLab по Helm Chart](https://docs.gitlab.com/charts/)
- [Настройка MetalLB](../Networking/metallb.md)
