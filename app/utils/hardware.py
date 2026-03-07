"""Hardware profiling utilities for dynamic model scaling."""

import logging

logger = logging.getLogger(__name__)

def get_vram_gb() -> float:
    """Detect available GPU VRAM in gigabytes.
    
    Returns 0.0 if no CUDA device is found, allowing graceful fallback to CPU thresholds.
    """
    try:
        import torch
        if not torch.cuda.is_available():
            return 0.0
            
        # Get properties of the primary device (device 0)
        props = torch.cuda.get_device_properties(0)
        total_memory_bytes = props.total_memory
        
        # Convert to GB
        total_memory_gb = total_memory_bytes / (1024 ** 3)
        return total_memory_gb
        
    except ImportError:
        logger.warning("PyTorch not available to check VRAM.")
        return 0.0
    except Exception as e:
        logger.warning(f"Failed to detect VRAM: {e}")
        return 0.0
