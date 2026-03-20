# OOM Killer in Containers

## OOM Killer в контейнерах

В контейнерах (Docker, Kubernetes) OOM Killer работает на двух уровнях:

| Уровень | Механизм | Результат |
| :--- | :--- | :--- |
| **Хост** | Ядро Linux | Убивает процесс контейнера |
| **Контейнер** | cgroups memory.limit | OOM внутри контейнера |

**Kubernetes QoS классы:**

| QoS класс | oom_score_adj | Описание |
| :--- | :--- | :--- |
| **Guaranteed** | -998 |Highest защита (лимита = request) |
| **Burstable** | 2–999 | Средняя защита |
| **BestEffort** | 1000 | Первый кандидат на удаление |

---

## Культурные отсылки

Выражение "[PRESS F TO PAY RESPECT](https://en.wikipedia.org/wiki/Press_F_to_pay_respects)" стало популярным мемом после его появления в игре Call of Duty: Advanced Warfare. Существует предположение, что один из контрибьюторов в ядро Linux (mchehab) намеренно использовал "f" как триггер для `sysrq-trigger`, отсылая к этому мему. Это совпадение или намеренная шутка, но оно добавляет неожиданный культурный контекст к работе системных инженеров.

---

**См. также:**

* [Механизм OOM Killer](./oom_killer_mechanism.md)
* [Управление поведением OOM Killer](./oom_killer_management.md)
* [Иерархия применения лимитов](./limits_hierarchy.md)
