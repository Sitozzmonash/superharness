from super_harness import HTTPRAGProvider, KnowledgeRouter

router = KnowledgeRouter(rag=HTTPRAGProvider())
rag_tool = router.tools()[0]
print(rag_tool.qualified_name, rag_tool.description)
