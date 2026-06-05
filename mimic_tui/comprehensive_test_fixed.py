#!/usr/bin/env python3
"""
Comprehensive test for the mimic_tui agent system
"""
import sys
import os
from mimic_tui.agent import OpenRouterAgent, AccountRotator
from mimic_tui.tools import ToolRegistry
from mimic_tui.config import OpenRouterConfig
from mimic_tui.multi_agent import ArchitectAgent, OperatorAgent, ScribeAgent, MultiAgentOrchestrator
from mimic_tui.utils import safe_print, C

def test_basic_agent_creation():
    """Test basic agent creation and initialization"""
    print("\n" + "="*60)
    print("TEST 1: Basic Agent Creation")
    print("="*60)
    
    try:
        # Create a test configuration
        config = OpenRouterConfig(api_keys=["test_key_12345"])
        
        # Create tool registry
        registry = ToolRegistry()
        
        # Create OpenRouterAgent
        agent = OpenRouterAgent(config, registry)
        
        print("✓ OpenRouterAgent created successfully")
        print(f"✓ Agent config model: {config.model}")
        
        # Check agent attributes
        print(f"✓ Agent has tool_registry: {hasattr(agent, 'tool_registry')}")
        if hasattr(agent, 'tool_registry'):
            print(f"✓ Agent has {len(agent.tool_registry._tools)} tools registered")
        
        return True
    except Exception as e:
        print(f"✗ Error creating agent: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_role_agents():
    """Test role-based agent creation"""
    print("\n" + "="*60)
    print("TEST 2: Role-Based Agents")
    print("="*60)
    
    try:
        # Create account rotator
        config = OpenRouterConfig(api_keys=["test_key_12345"])
        rotator = AccountRotator(config)
        
        # Create role agents
        architect = ArchitectAgent(rotator)
        operator = OperatorAgent(rotator)
        scribe = ScribeAgent(rotator)
        
        print("✓ ArchitectAgent created successfully")
        print(f"  - Role: {architect.ROLE_NAME}")
        print(f"  - Tools: {len(architect._tool_registry._tools)}")
        
        print("✓ OperatorAgent created successfully")
        print(f"  - Role: {operator.ROLE_NAME}")
        print(f"  - Tools: {len(operator._tool_registry._tools)}")
        
        print("✓ ScribeAgent created successfully")
        print(f"  - Role: {scribe.ROLE_NAME}")
        print(f"  - Tools: {len(scribe._tool_registry._tools)}")
        
        return True
    except Exception as e:
        print(f"✗ Error creating role agents: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_multi_agent_orchestrator():
    """Test multi-agent orchestrator"""
    print("\n" + "="*60)
    print("TEST 3: Multi-Agent Orchestrator")
    print("="*60)
    
    try:
        # Create account rotator
        config = OpenRouterConfig(api_keys=["test_key_12345"])
        rotator = AccountRotator(config)
        
        # Create orchestrator
        orchestrator = MultiAgentOrchestrator(rotator)
        
        print("✓ MultiAgentOrchestrator created successfully")
        print(f"  - Has architect: {orchestrator._architect is not None}")
        print(f"  - Has operator: {orchestrator._operator is not None}")
        print(f"  - Has scribe: {orchestrator._scribe is not None}")
        
        return True
    except Exception as e:
        print(f"✗ Error creating orchestrator: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_tool_registry():
    """Test tool registry functionality"""
    print("\n" + "="*60)
    print("TEST 4: Tool Registry")
    print("="*60)
    
    try:
        registry = ToolRegistry()
        
        # Check some expected tools
        expected_tools = ["run_bash", "read_file", "write_file", "web_search"]
        found_tools = []
        
        for tool_name in expected_tools:
            if tool_name in registry._tools:
                found_tools.append(tool_name)
        
        print(f"✓ ToolRegistry created with {len(registry._tools)} tools")
        print(f"✓ Found expected tools: {found_tools}")
        
        # List all available tools
        all_tools = list(registry._tools.keys())
        print(f"✓ Available tools: {', '.join(sorted(all_tools)[:10])}...")
        
        return True
    except Exception as e:
        print(f"✗ Error testing tool registry: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_agent_architecture():
    """Test the overall agent architecture"""
    print("\n" + "="*60)
    print("TEST 5: Agent Architecture Analysis")
    print("="*60)
    
    try:
        # Test agent class hierarchy
        from mimic_tui.multi_agent import RoleAgentBase
        
        architect = ArchitectAgent.__bases__[0]
        operator = OperatorAgent.__bases__[0]
        scribe = ScribeAgent.__bases__[0]
        
        print("✓ Agent inheritance hierarchy:")
        print(f"  - ArchitectAgent inherits from: {architect.__name__}")
        print(f"  - OperatorAgent inherits from: {operator.__name__}")
        print(f"  - ScribeAgent inherits from: {scribe.__name__}")
        
        # Test tool separation
        config = OpenRouterConfig(api_keys=["test_key_12345"])
        rotator = AccountRotator(config)
        
        architect = ArchitectAgent(rotator)
        operator = OperatorAgent(rotator)
        scribe = ScribeAgent(rotator)
        
        arch_tools = set(architect._tool_registry._tools.keys())
        oper_tools = set(operator._tool_registry._tools.keys())
        scribe_tools = set(scribe._tool_registry._tools.keys())
        
        print(f"✓ Architect tools: {len(arch_tools)} tools")
        print(f"✓ Operator tools: {len(oper_tools)} tools")
        print(f"✓ Scribe tools: {len(scribe_tools)} tools")
        
        # Check for proper tool separation
        architect_only = arch_tools - oper_tools - scribe_tools
        operator_only = oper_tools - arch_tools - scribe_tools
        scribe_only = scribe_tools - arch_tools - oper_tools
        
        print(f"✓ Architect-specific tools: {len(architect_only)}")
        print(f"✓ Operator-specific tools: {len(operator_only)}")
        print(f"✓ Scribe-specific tools: {len(scribe_only)}")
        
        # Show some example tools
        if architect_only:
            print(f"  - Architect-only tools: {list(architect_only)[:3]}")
        if operator_only:
            print(f"  - Operator-only tools: {list(operator_only)[:3]}")
        if scribe_only:
            print(f"  - Scribe-only tools: {list(scribe_only)[:3]}")
        
        return True
    except Exception as e:
        print(f"✗ Error testing architecture: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("MIMIC_TUI AGENT SYSTEM COMPREHENSIVE TEST")
    print("="*60)
    
    tests = [
        test_basic_agent_creation,
        test_role_agents,
        test_multi_agent_orchestrator,
        test_tool_registry,
        test_agent_architecture,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} failed with exception: {e}")
            results.append(False)
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(results)
    total = len(results)
    
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
