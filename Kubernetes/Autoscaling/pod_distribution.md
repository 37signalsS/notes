# Распределение Подов и Устойчивость

Для эффективного масштабирования и высокой доступности важно не только количество реплик, но и их правильное **распределение** по инфраструктуре (узлам, зонам доступности). Kubernetes предоставляет несколько механизмов для управления размещением подов.

## Pod Anti-Affinity

**Pod Anti-Affinity** — это правило, которое указывает планировщику Kubernetes **не размещать** определенные поды на одном и том же узле, в одной и той же зоне доступности или регионе.

**Основная цель:** Повысить отказоустойчивость. Если один узел или зона выйдет из строя, приложение продолжит работать, так как его реплики распределены по разным местам.

**Пример:**
`podAntiAffinity` можно настроить так, чтобы поды одного и того же `Deployment` (например, с меткой `app: my-frontend`) не попадали на один и тот же узел.

```yaml
# ... в spec.template.spec пода
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

## Topology Spread Constraints (Ограничения по топологии)

**Topology Spread Constraints** — это более гибкий и мощный механизм для равномерного распределения подов по различным доменам топологии (узлам, зонам, регионам).

В отличие от `podAntiAffinity`, который просто запрещает размещение, `topologySpreadConstraints` стремится к **равномерному балансу**.

**Пример:**
Это правило говорит планировщику, что разница в количестве подов с меткой `app: my-app` между любыми двумя зонами доступности не должна превышать 1.

```yaml
# ... в spec.template.spec пода
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

Использование этих механизмов крайне важно для построения отказоустойчивых систем, где потеря одного узла или даже целой зоны доступности не приводит к полному отказу сервиса.
