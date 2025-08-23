# rpc.py
import logging
import requests
from typing import Any, Dict, List, Optional
from web3 import Web3
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# 全局复用的 Session，带重试与连接池
_session: Optional[requests.Session] = None

def _get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retries = Retry(
            total=5,                # 总重试次数
            connect=3,              # 连接失败重试
            read=3,                 # 读超时重试
            backoff_factor=1.0,     # 退避：1, 2, 4, ...
            status_forcelist=[502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=50)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _session = s
    return _session

def rpc_call(endpoint: str, method: str, params: List[Any], timeout: int = 20) -> Any:
    """
    低层 JSON-RPC 调用。
    可能抛出 requests.HTTPError / requests.ReadTimeout / RuntimeError（RPC error）。
    """
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    headers = {"Content-Type": "application/json"}
    r = _get_session().post(endpoint, json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if "error" in data and data["error"]:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data.get("result")

def get_block_number(endpoint: str) -> int:
    """获取最新区块号（十进制整数）"""
    result = rpc_call(endpoint, "eth_blockNumber", [])
    return int(result, 16)

def get_block_with_txs(endpoint: str, block_number: int) -> Dict[str, Any]:
    """
    获取指定区块（含交易列表）。
    返回字典；若获取失败，可能返回 {}。
    """
    hex_bn = hex(block_number)
    result = rpc_call(endpoint, "eth_getBlockByNumber", [hex_bn, True])
    return result or {}

def get_eth_balance_wei(endpoint: str, address: str) -> int:
    """获取地址余额（单位：Wei）"""
    result = rpc_call(endpoint, "eth_getBalance", [address, "latest"])
    return int(result, 16)

def from_wei(wei: int):
    """Wei -> Ether，返回 Decimal，可直接用于 f-string"""
    return Web3.from_wei(wei, "ether")

def to_checksum(address: str) -> str:
    """转换为校验和地址（EIP-55）"""
    return Web3.to_checksum_address(address)

# 可选：直接运行本文件做连通性快速测试
if __name__ == "__main__":
    import os
    INFURA_HTTP = os.getenv("INFURA_HTTP")
    if not INFURA_HTTP:
        print("请先设置环境变量 INFURA_HTTP")
    else:
        try:
            latest = get_block_number(INFURA_HTTP)
            print("Latest block:", latest)
        except Exception as e:
            logging.exception(e)
            print("RPC 测试失败：", e)
