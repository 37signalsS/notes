# Диагностика и решение распространенных ошибок в Kubernetes

Это обзор распространенных ошибок в Kubernetes, их причин, диагностики и решений.

Каждая из следующих заметок подробно описывает конкретную проблему:
*   [Pod в состоянии `Pending`](./pod_pending.md)
*   [Проблемы с загрузкой образов (`ImagePullBackOff` / `ErrImagePull`)](./pod_image_pull_errors.md)
*   [Поды в состоянии `CrashLoopBackOff`](./pod_crash_loop_back_off.md)
*   [Ошибки конфигурации контейнеров (`CreateContainerConfigError`)](./create_container_config_error.md)
*   [Поды, убитые из-за нехватки памяти (`OOMKilled`)](./oomkilled_pods.md)
*   [Проблемы с доступностью узлов (`NodeNotReady` / `Node Unreachable`)](./node_unavailability.md)
*   [Ошибки доступа к API (`Forbidden` / `Unauthorized`)](./api_access_forbidden.md)
*   [Проблемы с завершением подов (`Terminating`)](./pod_terminating_issues.md)
*   [Выселенные поды (`Evicted`)](./pod_evicted.md)
