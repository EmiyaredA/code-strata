import io.shiftleft.semanticcpg.language._
import flatgraph.{Accessors, GNode}
import java.nio.file.{Files, Paths}
import scala.collection.mutable

@main def exportFocused(cpgFile: String, outFile: String, maxDetailNodes: Int = 50000): Unit = {
  importCpg(cpgFile)
  val nodes = mutable.LinkedHashMap.empty[Long, GNode]
  val detailed = mutable.LinkedHashSet.empty[Long]
  val paths = mutable.Map.empty[Long, String]
  val owners = mutable.Map.empty[Long, Long]
  val methods = cpg.method.isExternal(false).l.sortBy(m => (m.filename, m.lineNumber.getOrElse(0), m.fullName))
  methods.foreach(m => nodes(m.id) = m)
  cpg.file.foreach(n => nodes(n.id) = n)
  cpg.typeDecl.isExternal(false).filter(_.lineNumber.isDefined).foreach(n => nodes(n.id) = n)
  val roots = if (methods.size < 500) methods else methods.filter(m =>
    m.lineNumber.isDefined && !m.name.startsWith("<") && m.name != ":program" &&
    !m.filename.contains("/fixtures/") && !m.filename.contains("_vendor/")).take(40)
  var truncated = false
  roots.foreach { m =>
    m.ast.foreach { n =>
      if (detailed.size < maxDetailNodes) {
        nodes(n.id) = n
        detailed += n.id
      } else truncated = true
    }
    m.callIn.take(100).foreach { call =>
      if (detailed.size < maxDetailNodes) {
        nodes(call.id) = call
        detailed += call.id
        paths(call.id) = call.method.filename
        owners(call.id) = call.method.id
      } else truncated = true
    }
  }
  val keptLabels = Set("AST", "CALL", "REF", "CFG", "REACHING_DEF", "IMPORTS")
  // Include direct semantic targets without expanding the entire graph.
  detailed.toList.foreach { id =>
    Accessors.getEdgesOut(nodes(id)).foreach { edge =>
      if (keptLabels.contains(edge.label) && edge.label != "AST") nodes(edge.dst.id) = edge.dst
    }
  }
  def json(value: Any): ujson.Value = value match {
    case null => ujson.Null
    case x: String => ujson.Str(x)
    case x: Boolean => ujson.Bool(x)
    case x: Int => ujson.Num(x)
    case x: Long => ujson.Num(x.toDouble)
    case x: Double => ujson.Num(x)
    case x: Array[?] => ujson.Arr.from(x.iterator.map(json))
    case x: Iterable[?] => ujson.Arr.from(x.iterator.map(json))
    case x => ujson.Str(x.toString)
  }
  val fields = Map("NAME" -> "name", "CODE" -> "code", "FULL_NAME" -> "fullName", "TYPE_FULL_NAME" -> "type",
    "FILENAME" -> "filename", "LINE_NUMBER" -> "line", "COLUMN_NUMBER" -> "column", "LINE_NUMBER_END" -> "endLine",
    "COLUMN_NUMBER_END" -> "endColumn", "ORDER" -> "order", "IS_EXTERNAL" -> "external", "DISPATCH_TYPE" -> "dispatchType",
    "ARGUMENT_INDEX" -> "argumentIndex", "CONTROL_STRUCTURE_TYPE" -> "controlType", "METHOD_FULL_NAME" -> "methodFullName",
    "IMPORTED_ENTITY" -> "importedEntity", "IMPORTED_AS" -> "importedAs")
  val coreEdges = mutable.ArrayBuffer.empty[flatgraph.Edge]
  val dataEdges = mutable.ArrayBuffer.empty[flatgraph.Edge]
  var coreEdgesTruncated = false
  var dataEdgesTruncated = false
  nodes.valuesIterator.foreach { n =>
    Accessors.getEdgesOut(n).foreach { e =>
      if (keptLabels.contains(e.label) && nodes.contains(e.dst.id)) {
        if (e.label == "REACHING_DEF") {
          if (dataEdges.size < 50000) dataEdges += e else dataEdgesTruncated = true
        } else {
          if (coreEdges.size < 200000) coreEdges += e else coreEdgesTruncated = true
        }
      }
    }
  }
  val writer = Files.newBufferedWriter(Paths.get(outFile))
  def emit(value: ujson.Value): Unit = { writer.write(ujson.write(value)); writer.newLine() }
  try {
    emit(ujson.Obj("recordType" -> "metadata", "indexMethods" -> methods.size, "detailedNodes" -> detailed.size,
      "truncated" -> truncated, "maxDetailNodes" -> maxDetailNodes,
      "coreEdgeLimit" -> 200000, "dataEdgeLimit" -> 50000,
      "coreEdgesTruncated" -> coreEdgesTruncated, "dataEdgesTruncated" -> dataEdgesTruncated,
      "scope" -> "global declaration index plus bounded function bodies and incoming callsites; not a full graph export",
      "detailRoots" -> ujson.Arr.from(roots.map(m => ujson.Obj("name" -> m.fullName, "filename" -> m.filename)))))
    nodes.valuesIterator.foreach { n =>
      val obj = ujson.Obj("recordType" -> "node", "id" -> n.id.toString, "label" -> n.label)
      Accessors.getNodeProperties(n).foreach { case (key, value) =>
        fields.get(key).foreach { destination =>
          val v = json(value)
          val scalar = v match { case a: ujson.Arr => a.value.headOption.getOrElse(ujson.Null); case other => other }
          if (destination == "code" && scalar.isInstanceOf[ujson.Str] && scalar.str.length > 4096) {
            obj(destination) = scalar.str.take(4096)
            obj("codeTruncated") = true
          } else obj(destination) = scalar
        }
      }
      paths.get(n.id).foreach(p => obj("filename") = p)
      owners.get(n.id).foreach(p => obj("owner") = p.toString)
      obj("detail") = detailed.contains(n.id)
      emit(obj)
    }
    (coreEdges.iterator ++ dataEdges.iterator).foreach { e =>
          emit(ujson.Obj("recordType" -> "edge", "label" -> e.label,
            "source" -> e.src.id.toString, "target" -> e.dst.id.toString,
            "variable" -> Option(e.property).map(x => json(x)).getOrElse(ujson.Null)))
    }
  } finally writer.close()
  cpg.close
}
