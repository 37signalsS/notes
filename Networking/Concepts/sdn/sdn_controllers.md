# SDN Контроллеры

## Сравнение контроллеров

| Контроллер | Язык | Архитектура | Кластеризация | Лицензия | Примеры использования |
|------------|------|-------------|---------------|----------|---------------------|
| **ONOS** | Java | Модульная | Да (Raft) | Apache 2.0 | Телеком, крупные сети |
| **OpenDaylight** | Java | MD-SAL | Да | EPL 1.0 | Enterprise, NFV |
| **Ryu** | Python | Простая | Нет | Apache 2.0 | Исследования, небольшие сети |
| **Floodlight** | Java | Монолит | Нет | Apache 2.0 | Образование, PoC |
| **POX** | Python | Простая | Нет | Apache 2.0 | Образование, прототипы |
| **Tungsten Fabric** | Java | Масштабируемая | Да | Apache 2.0 | Cloud, OpenStack |

## ONOS (Open Network Operating System)

```java
// Пример приложения ONOS
@Component(immediate = true)
public class MyApp {
    
    @Reference(cardinality = ReferenceCardinality.MANDATORY)
    protected FlowRuleService flowRuleService;
    
    @Activate
    protected void activate() {
        // Создание flow rule
        TrafficSelector selector = DefaultTrafficSelector.builder()
            .matchEthType(Ethernet.TYPE_IPV4)
            .matchIPDst(IpPrefix.valueOf("10.0.0.0/24"))
            .build();
        
        TrafficTreatment treatment = DefaultTrafficTreatment.builder()
            .setOutput(PortNumber.portNumber(2))
            .build();
        
        FlowRule flowRule = DefaultFlowRule.builder()
            .forDevice(deviceId)
            .withSelector(selector)
            .withTreatment(treatment)
            .withPriority(50000)
            .makeTemporary(60)
            .build();
        
        flowRuleService.applyFlowRules(flowRule);
    }
}
```

## Ryu (Python)

```python
# Простой SDN контроллер на Ryu
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3

class SimpleHub(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # Установить flow: flood все пакеты
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        
        self.add_flow(datapath, 0, match, actions)
    
    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        
        mod = parser.OFPFlowMod(
            datapath=datapath, priority=priority,
            match=match, instructions=inst)
        
        datapath.send_msg(mod)
```
