import io.shiftleft.semanticcpg.language._
import java.nio.file.{Files, Paths}

@main def probe(cpgFile: String, outFile: String, withDataflow: Boolean = false): Unit = {
  importCpg(cpgFile)
  val initialOverlays = cpg.metaData.l.flatMap(_.overlays).toList
  val hasDataflow = initialOverlays.exists(x => x == "ossdataflow" || x == "dataflowOss")
  var dataflowStatus = if (hasDataflow) "already-present" else "not-requested"
  if (withDataflow) {
    try {
      if (!hasDataflow) {
        run.ossdataflow
        dataflowStatus = "applied"
      }
    } catch {
      case e: Throwable => dataflowStatus = "failed: " + e.toString
    }
  }
  val samples = cpg.method.isExternal(false).filter(m => m.lineNumber.isDefined && !m.name.startsWith("<") && m.name != ":program").toList.sortBy(m => (m.filename, m.lineNumber.getOrElse(0), m.fullName)).take(20).map { m =>
    val start = System.nanoTime()
    val targets = m.ast.isCall.filter(_.method.id == m.id).callee.fullName.l
    val callers = m.callIn.method.fullName.toSet.toList.sorted
    val identifiers = m.ast.isIdentifier.size
    val controls = m.ast.isControlStructure.size
    val parameters = m.parameter.size
    ujson.Obj("method" -> m.fullName, "filename" -> m.filename,
      "line" -> m.lineNumber.getOrElse(0), "targets" -> ujson.Arr.from(targets), "callers" -> ujson.Arr.from(callers),
      "identifiers" -> identifiers, "controls" -> controls, "parameters" -> parameters,
      "milliseconds" -> ((System.nanoTime() - start).toDouble / 1000000.0))
  }.toList
  val result = ujson.Obj("dataflowStatus" -> dataflowStatus,
    "initialOverlays" -> ujson.Arr.from(initialOverlays),
    "queryScope" -> "same Joern session: function calls, identifiers, controls, parameters",
    "samples" -> ujson.Arr.from(samples))
  Files.writeString(Paths.get(outFile), ujson.write(result, indent = 2))
  cpg.close
}
