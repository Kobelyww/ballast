# 呼叫与升级（Paging）

## 何时必须呼叫
sev1 / sev2 且存在 firing 告警时必须呼叫 SRE 值班。
sev3 / sev4 不呼叫，进入服务团队队列处理。
告警已恢复（无 firing）时禁止补叫，只登记复盘。

## 需要人类负责的情形
payments tier 的 sev1/sev2 故障必须有人类 owner，Agent 只能提供事实与建议。
同一故障存在 3 条及以上跨服务 firing 告警时属于多服务影响，必须转人工。

## 复盘要求
关闭故障前必须完成：acknowledge（人工接单）、review（登记根因与时间线）、
影响客户时的 status page 更新。缺项时 close_incident 会被拒绝。
