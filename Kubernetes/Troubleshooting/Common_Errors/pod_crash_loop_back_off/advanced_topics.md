# Pod в состоянии `CrashLoopBackOff`: Дополнительная информация

## Автоматизация диагностики

```bash
#!/bin/bash
# Скрипт быстрой диагностики CrashLoopBackOff

POD=$1

echo "=== Статус пода ==="
kubectl get pod $POD -o wide

echo -e "\n=== Описание ==="
kubectl describe pod $POD | grep -A 10 "State:\|Last State:"

echo -e "\n=== Логи (предыдущие) ==="
kubectl logs $POD --previous --tail=50

echo -e "\n=== События ==="
kubectl get events --field-selector involvedObject.name=$POD --sort-by='.lastTimestamp'
```

---

## Связь с другими ошибками

| Ошибка | Связь с CrashLoopBackOff |
|--------|--------------------------|
| `OOMKilled` | Частая причина CrashLoopBackOff |
| `ImagePullBackOff` | Предшествует CrashLoopBackOff (образ не скачан) |
| `CreateContainerConfigError` | Предшествует CrashLoopBackOff (конфигурация) |
| `Error` (Exit Code 1) | Непосредственная причина |

---

## Best Practices

| Практика | Описание |
|----------|----------|
| **Всегда смотрите `--previous` логи** | Основной источник информации |
| **Проверяйте Exit Code** | Указывает на тип ошибки |
| **Используйте startupProbe** | Для приложений с долгим стартом |
| **Настраивайте livenessProbe корректно** | Избегайте ложных срабатываний |
| **Логируйте в stdout/stderr** | Kubernetes собирает только эти потоки |

---

## Ссылки

- [Kubernetes Pod Lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)
- [Configure Liveness, Readiness and Startup Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [Debug Pods](https://kubernetes.io/docs/tasks/debug/debug-pod/)

---

## Ссылки на связанные файлы

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Практические сценарии](./practical_scenarios.md) — диагностика и решения
