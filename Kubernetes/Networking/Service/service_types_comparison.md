# Сравнительная таблица типов Service

Эта таблица предоставляет краткую сводку по основным типам `Service` в Kubernetes, их сценариям использования и ключевым характеристикам.

| Тип | Основной сценарий | Доступность | IP-адрес | Балансировка |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **ClusterIP** | Внутренние коммуникации (backend ↔ db) | Только внутри кластера | Стабильный виртуальный `ClusterIP` | Да (round-robin) | [Подробнее](./service_type_clusterip.md) |
| **NodePort** | Разработка, отладка, bare-metal | Снаружи, через `IP_узла:NodePort` | `ClusterIP` + порт на каждом узле | Да (round-robin) | [Подробнее](./service_type_nodeport.md) |
| **LoadBalancer** | Production-приложения в облаке | Снаружи, через публичный IP балансировщика | `ClusterIP` + `NodePort` + внешний IP | Да (облачным провайдером) | [Подробнее](./service_type_loadbalancer.md) |
| **ExternalName**| Доступ к внешним ресурсам по DNS-имени | N/A (только DNS) | Нет (возвращает CNAME) | Нет | [Подробнее](./service_type_externalname.md) |
| **Headless** | Stateful-приложения (`StatefulSet`) | Прямой доступ к подам по их DNS-именам | Нет (DNS возвращает IP подов) | Нет (клиентская) | [Подробнее](./service_type_headless.md) |

---

### Дополнительные концепции

Помимо основных типов, существуют важные поля и концепции, расширяющие функциональность сервисов:

| Концепция | Описание |
| :--- | :--- |
| **ExternalIPs** | Привязка сервиса к одному или нескольким статическим внешним IP, которые вы контролируете. | [Подробнее](./service_externalips.md) |
| **`externalTrafficPolicy: Local`** | Настройка для `NodePort` и `LoadBalancer`, сохраняющая исходный IP-адрес клиента. Трафик направляется только на локальные поды. | [Подробнее в NodePort](./service_type_nodeport.md#externaltrafficpolicy-local) |

### Связанные ресурсы

- **Обзорная статья**: [Service Overview](./service_overview.md)
- **Сводка и иерархия**: [Service Types Summary](./service_types_summary.md)
