# Распределение Подов и Устойчивость

## Определения

**Pod Anti-Affinity** — правило планирования, запрещающее размещение определенных подов на одном узле или в одной зоне доступности.

**Topology Spread Constraints** — механизм равномерного распределения подов по доменам топологии (узлам, зонам, регионам).

**Topology Key** — метка узла, определяющая домен топологии (`kubernetes.io/hostname`, `topology.kubernetes.io/zone`).

## Основные концепции

### Сравнение механизмов

| Механизм | Подход | Применение |
|----------|--------|------------|
| Pod Anti-Affinity | Запрет размещения | Жесткие требования к изоляции |
| Topology Spread | Балансировка | Равномерное распределение |

### Pod Anti-Affinity

Запрещает совместное размещение подов с определенными метками в пределах указанного домена.

**Уровни строгости:**
- `requiredDuringSchedulingIgnoredDuringExecution` — жесткое требование
- `preferredDuringSchedulingIgnoredDuringExecution` — предпочтительное

### Topology Spread Constraints

Стремится к равномерному распределению подов между доменами топологии.

## Практические сценарии

### Pod Anti-Affinity

```yaml
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchExpressions:
        - key: app
          operator: In
          values:
          - my-frontend
      topologyKey: "kubernetes.io/hostname"
```
-   `requiredDuringSchedulingIgnoredDuringExecution`: Жесткое правило. Если планировщик не может его выполнить, под не будет запущен.
-   `topologyKey: "kubernetes.io/hostname"`: Указывает, что правило применяется в пределах одного узла.
### Topology Spread Constraints

```yaml
topologySpreadConstraints:
- maxSkew: 1
  topologyKey: "topology.kubernetes.io/zone"
  whenUnsatisfiable: DoNotSchedule
  labelSelector:
    matchLabels:
      app: my-app
```
-   `maxSkew`: Максимально допустимая разница в количестве подов.
-   `topologyKey`: Домен, в котором нужно соблюдать баланс (например, `zone` или `hostname`).
-   `whenUnsatisfiable`: Что делать, если правило невозможно выполнить (`DoNotSchedule` — не размещать, `ScheduleAnyway` — разместить, но нарушить правило).


### Комбинированное использование

Для максимальной отказоустойчивости используйте оба механизма:
- Anti-Affinity для критичных компонентов (базы данных)
- Topology Spread для равномерной нагрузки между зонами

## Дополнительная информация

### Связь с масштабированием

- [Horizontal Pod Autoscaler](hpa_detailed.md) — созданные HPA поды распределяются согласно правилам
- [Pod Disruption Budget](pod_disruption_budget.md) — совместное использование обеспечивает доступность при потере узла
- [Паттерны масштабирования](scaling_patterns.md) — шардирование требует особого внимания к распределению

### Рекомендации

- Используйте `topology.kubernetes.io/zone` для мульти-зонных кластеров
- Настраивайте `maxSkew` с учетом ожидаемого масштаба
- Тестируйте поведение при отказе узла
- Для stateful-приложений приоритизируйте Pod Anti-Affinity

### Ограничения

- Требуется достаточное количество узлов/зон
- Может блокировать масштабирование при недостатке ресурсов
- Не защищает от недобровольных прерываний без PDB
