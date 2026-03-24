from __future__ import annotations

from pathlib import Path

from ..context.context_store import discover_artifact_files, discover_p4_files
from ..pipeline.models import BenchmarkCase


CASE_STUDY_ROOT = Path("/home/gosh/P4LTL/Artifact/benchmark/Temporal Verification/Case Study")
SAGEFUZZ_ROOT = Path("/home/gosh/SageFuzz/P4")


def load_default_benchmark_cases() -> list[BenchmarkCase]:
    return _case_study_cases() + _sagefuzz_cases()


def _case_study_cases() -> list[BenchmarkCase]:
    selected = [
        (
            "Blink",
            "2.p4ltl",
            "在持续有合法 TCP 业务包出现，且 meta.use_blink == 1、hdr.ipv4.ttl != 1 的前提下，"
            "如果某个 id=a 的 nh_avaibility_1[a] 当前为 0，那么下一步开始一旦该可用性变为 1，"
            "对应的 sw_sum_0[a] 应大于 threshold_registers_0[a]。"
        ),
        (
            "Bfs",
            "1.p4ltl",
            "在持续有合法 bfsTag，且 meta.local_metadata.out_port != 0 或 meta.local_metadata.pkt_par != 0 的前提下，"
            "只要 meta.local_metadata.is_completed == 0，就应一直保持未完成状态，"
            "直到 meta.local_metadata.out_port == meta.local_metadata.pkt_par。"
        ),
        (
            "CoDel",
            "3.p4ltl",
            "对于任意队列 a，在持续有 ingress_port == 1、meta.codel.queue_id == a，且 meta.codel.drop_next >= meta.codel.drop_time 的前提下，"
            "如果 old(r_state_dropping[a]) == 1，那么程序应一直保持“当 meta.codel.time_now >= meta.codel.drop_next 时发生 drop”，"
            "直到 standard_metadata.deq_timedelta < 5000。"
        ),
        (
            "Dfs",
            "5.p4ltl",
            "在持续有合法 dfsTag，且 meta.local_metadata.out_port != 0 或 meta.local_metadata.pkt_par != 0 的前提下，"
            "只要 meta.local_metadata.is_completed == 0，就应一直保持未完成状态，"
            "直到 meta.local_metadata.out_port == meta.local_metadata.pkt_par。"
        ),
        (
            "P4NIS",
            "9.p4ltl",
            "在数据包入端口为 0、目的 MAC 地址不为 0xffffffffffff、目的 IP 地址不等于 0x7b7b7b7b、"
            "源 MAC 不为 0 的合法业务包持续进入交换机的前提下，程序应反复地把这类包转发到端口 1、2、3，"
            "也就是每个端口都要无限次出现。"
        ),
        (
            "P4sp",
            "11.p4ltl",
            "在 hdr.ethernet.etherType == 0xDD01 且 meta.secondary != meta.primary 的前提下，"
            "程序不应一直处于“secondary 在保护期内仍被接受”的状态；"
            "这个不安全状态必须保持不成立，直到已经超过保护期。"
        ),
        (
            "NdN",
            "6.p4ltl",
            "在持续有 ingress_port 处于 1 到 7 之间、meta.name_metadata.components != 0，且 meta.name_metadata.name_hash == a 的前提下，"
            "当 meta.flow_metadata.packetType == 0x06 且当前未 drop 时，下一步开始应保持这类 0x06 包被 drop，"
            "直到出现 meta.flow_metadata.packetType == 0x05 且未 drop 的情况；"
            "同时相关控制平面规则应保证当 hasFIBentry == 1 时选择 updatePit_entry。"
        ),
    ]
    cases: list[BenchmarkCase] = []
    for folder, gold_name, intent in selected:
        root = CASE_STUDY_ROOT / folder
        cases.append(
            BenchmarkCase(
                case_id=f"case-study:{folder}",
                suite="case-study",
                intent=intent,
                admin_description=f"Use the {folder} case-study program and its existing benchmark artifacts as context.",
                root_dir=str(root),
                p4_program_paths=discover_p4_files(root),
                artifact_paths=discover_artifact_files(root),
                gold_spec_paths=[str(root / gold_name)],
                extra_constraints=[
                    "Do not use P4xos.",
                    "Prefer entities that can be justified by the case-study program or its artifacts.",
                ],
            )
        )
    return cases


def _sagefuzz_cases() -> list[BenchmarkCase]:
    def make_case(
        case_id: str,
        root_name: str,
        intent: str,
        admin_description: str,
    ) -> BenchmarkCase:
        root = SAGEFUZZ_ROOT / root_name
        return BenchmarkCase(
            case_id=case_id,
            suite="sagefuzz",
            intent=intent,
            admin_description=admin_description,
            root_dir=str(root),
            p4_program_paths=discover_p4_files(root),
            artifact_paths=discover_artifact_files(root),
        )

    return [
        make_case(
            case_id="sagefuzz:firewall:block-new-external",
            root_name="firewall",
            intent=(
                "验证状态防火墙的一部分核心意图：外部主机不能主动发起到内部网络的新 TCP 连接；"
                "当一个外部到内部的 TCP SYN 试图建立新连接时，程序应阻断或丢弃这类包。"
            ),
            admin_description=(
                "This is a stateful firewall implemented with a bloom filter in the data plane. "
                "Hosts h1 and h2 are internal; h3 and h4 are external. "
                "This case focuses only on blocking new external-to-internal connection attempts."
            ),
        ),
        make_case(
            case_id="sagefuzz:firewall:allow-return-traffic",
            root_name="firewall",
            intent=(
                "验证状态防火墙的另一部分核心意图：如果内部主机先建立了连接，"
                "那么外部主机的返回 TCP 流量应被允许通过，而不是一直被阻断。"
            ),
            admin_description=(
                "This is a stateful firewall with connection state tracked in the data plane. "
                "This case focuses on allowing reply traffic for already established connections."
            ),
        ),
        make_case(
            case_id="sagefuzz:link-monitor:collect-per-hop-utilization",
            root_name="link_monitor",
            intent=(
                "验证链路监控程序的一部分核心意图：当 probe 包穿过交换机时，程序应逐跳把出口链路利用率相关数据写入 probe 数据头。"
            ),
            admin_description=(
                "This program maintains per-port byte counters and timestamps, and writes monitoring information into source-routed probe packets."
            ),
        ),
        make_case(
            case_id="sagefuzz:link-monitor:deliver-monitoring-data",
            root_name="link_monitor",
            intent=(
                "验证链路监控程序的另一部分核心意图：probe 包最终应把收集到的链路利用率监控信息带到主机端用于观测。"
            ),
            admin_description=(
                "The monitoring information should survive the path traversal and be delivered to the host that receives and parses probe packets."
            ),
        ),
        make_case(
            case_id="sagefuzz:heavy-hitter:block-heavy-flow",
            root_name="Heavy_Hitter_Detector",
            intent=(
                "验证 heavy hitter 检测的一部分核心意图：当某个 TCP 流的计数超过阈值后，程序应阻断或丢弃该流。"
            ),
            admin_description=(
                "This program uses a counting bloom filter and a threshold to detect and block heavy hitter TCP flows."
            ),
        ),
        make_case(
            case_id="sagefuzz:heavy-hitter:forward-normal-flow",
            root_name="Heavy_Hitter_Detector",
            intent=(
                "验证 heavy hitter 检测的另一部分核心意图：未超过阈值的正常 TCP 流应继续被正常转发，而不是被误丢弃。"
            ),
            admin_description=(
                "Flows below the heavy-hitter threshold should continue through the IPv4 forwarding path."
            ),
        ),
        make_case(
            case_id="sagefuzz:fast-reroute:failover-to-lfa",
            root_name="Fast-Reroute",
            intent=(
                "验证快速重路由的一部分核心意图：当主下一跳对应链路故障时，交换机应立即选择无环备用下一跳转发流量。"
            ),
            admin_description=(
                "This program stores primary and backup next hops and reads local link state to reroute traffic immediately after adjacent link failure."
            ),
        ),
        make_case(
            case_id="sagefuzz:fast-reroute:use-primary-when-healthy",
            root_name="Fast-Reroute",
            intent=(
                "验证快速重路由的另一部分核心意图：当主链路正常时，程序应继续使用主下一跳，而不是无条件切到备用路径。"
            ),
            admin_description=(
                "The backup next hop should only be used when the primary link is down; otherwise the primary path remains active."
            ),
        ),
        make_case(
            case_id="sagefuzz:load-balancing:add-telemetry-in-network",
            root_name="Congestion_Aware_Load_Balancing",
            intent=(
                "验证拥塞感知负载均衡的一部分核心意图：当 TCP 包在网络内部传输时，程序应在网络内部维护 telemetry 信息以携带路径上的队列深度。"
            ),
            admin_description=(
                "This program adds a telemetry header inside the network and updates it with queue information as packets traverse switches."
            ),
        ),
        make_case(
            case_id="sagefuzz:load-balancing:remove-telemetry-before-host",
            root_name="Congestion_Aware_Load_Balancing",
            intent=(
                "验证拥塞感知负载均衡的另一部分核心意图：带 telemetry 的包在离开网络到达主机前，应去掉 telemetry 头并恢复正常以太网类型。"
            ),
            admin_description=(
                "Telemetry is only for in-network switches and should be removed before packets leave towards hosts."
            ),
        ),
        make_case(
            case_id="sagefuzz:load-balancing:reroute-congested-flow",
            root_name="Congestion_Aware_Load_Balancing",
            intent=(
                "验证拥塞感知负载均衡的核心闭环意图：当出口检测到流经历拥塞并触发通知后，入口交换机最终应把该流迁移到其他路径，避免长期停留在拥塞路径上。"
            ),
            admin_description=(
                "This program uses congestion notifications and flow re-hashing so that congested flows eventually move to another path."
            ),
        ),
    ]
