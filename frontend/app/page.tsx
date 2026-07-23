import Link from "next/link";
import "./landing.css";

const benefits = [
  ["01", "يفهم الاستشارة كما قيلت", "تفريغ طبي لحظي للعربية واللهجات المحلية، مع الحفاظ على المصطلحات السريرية باللغتين.", "Arabic clinical ASR"],
  ["02", "يصيغ ملاحظة SOAP مهيكلة", "يحوّل الحوار إلى ملاحظة قابلة للمراجعة وفق القالب الذي يختاره الطبيب لكل تخصص ونوع زيارة.", "Structured SOAP notes"],
  ["03", "يربط التوثيق بالترميز", "إرشاد سريري وترميزي مضمّن في موضعه، مبني على ملف المريض وكلام الزيارة مع إظهار المصدر.", "ICD-10-AM · ACHI · SBS"],
  ["04", "يبقي القرار بيد الطبيب", "تعديل بالنص أو الصوت أو محادثة الذكاء الاصطناعي، ثم اعتماد بشري صريح قبل إرسال أي بيانات.", "Human-in-the-loop"],
  ["05", "يرفع الزيارة إلى نظامك", "تصدير منظم إلى أنظمة المستشفى بصيغ متوافقة مع FHIR وNPHIES مع حالة رفع واضحة.", "FHIR / NPHIES ready"],
  ["06", "يحافظ على سيادة البيانات", "بنية مصممة للمنشآت السعودية، مع عزل بيانات كل منشأة وسجل تدقيق كامل.", "KSA data residency · PDPL"],
];

const steps = [
  ["01", "اختر القالب", "اختر قالب التلخيص المناسب للتخصص ونوع الزيارة."],
  ["02", "ابدأ الاستشارة", "يسجل Medify الحوار ويفرغه لحظيًا دون تعطيل التواصل مع المريض."],
  ["03", "راجع بذكاء", "راجع SOAP والإرشادات السريرية والترميزية في مساحة واحدة."],
  ["04", "اعتمد وارفع", "اعتماد بشري نهائي، ثم رفع الزيارة إلى نظام المستشفى."],
];

export default function LandingPage() {
  return (
    <main className="landing" dir="rtl">
      <header className="landing-nav">
        <div className="landing-shell nav-inner">
          <Link href="/" className="brand-link" aria-label="Medify — الصفحة الرئيسية"><img src="/brand/medify-logo-reversed-transparent.png" alt="Medify" /></Link>
          <nav className="nav-links" aria-label="التنقل الرئيسي"><a href="#solution">الحل</a><a href="#workflow">كيف يعمل</a><a href="#trust">الأمان</a></nav>
          <div className="nav-actions"><Link className="nav-login" href="/login">تسجيل الدخول</Link><Link className="button button-small" href="/register">اطلب عرضًا</Link></div>
        </div>
      </header>

      <section className="hero">
        <div className="hero-glow" aria-hidden="true" />
        <div className="landing-shell hero-grid">
          <div className="hero-copy">
            <div className="eyebrow"><span /> كاتب طبي ذكي صُمم للرعاية الصحية السعودية</div>
            <h1>أنصت لمريضك.<br /><em>اترك التوثيق لـ Medify.</em></h1>
            <p className="hero-lead">يحوّل Medify الاستشارة العربية إلى ملاحظة <bdi>SOAP</bdi> مهيكلة، بإرشاد سريري وترميزي مضمّن، جاهزة للمراجعة والاعتماد والرفع إلى نظام المستشفى.</p>
            <div className="hero-actions"><Link className="button button-primary" href="/register">اطلب عرضًا لمنشأتك <span aria-hidden="true">←</span></Link><a className="button button-ghost" href="#workflow"><span className="play" aria-hidden="true">▶</span> شاهد كيف يعمل</a></div>
            <div className="hero-note"><span className="shield" aria-hidden="true">✓</span><span>الإنسان يعتمد، والآلة تقترح — لا رفع قبل موافقة الطبيب.</span></div>
          </div>

          <div className="product-stage" aria-label="معاينة رحلة التوثيق داخل Medify">
            <div className="stage-orbit orbit-one" aria-hidden="true" /><div className="stage-orbit orbit-two" aria-hidden="true" />
            <div className="product-window">
              <div className="window-top"><div className="window-dots"><i /><i /><i /></div><span>زيارة جديدة · عيادة الباطنة</span><span className="live"><i /> تسجيل مباشر</span></div>
              <div className="patient-row"><div className="patient-avatar">م ع</div><div><strong>محمد العتيبي</strong><small>ملف المريض · آخر زيارة منذ 3 أشهر</small></div><span className="context-pill">تم تحميل السياق الطبي</span></div>
              <div className="transcript-card">
                <div className="card-label"><span className="mic">●</span> نص الاستشارة المباشر <bdi>00:08:42</bdi></div>
                <p><b>المريض:</b> الألم بدأ من ثلاثة أيام ويزيد بعد الأكل...</p><p><b>الطبيب:</b> هل يصاحبه غثيان أو ارتفاع في الحرارة؟</p>
                <div className="wave" aria-hidden="true">{[18,34,24,48,31,58,26,44,20,52,29,38,17,47,24,34].map((h, i) => <i key={i} style={{height: h}} />)}</div>
              </div>
              <div className="soap-card">
                <div className="soap-head"><div><span className="spark">✦</span><strong>ملاحظة SOAP</strong><small>تم إنشاؤها من الاستشارة وسياق المريض</small></div><span className="status">جاهزة للمراجعة</span></div>
                <div className="soap-line"><bdi>S</bdi><div><strong>Subjective</strong><p>ألم أعلى البطن منذ 3 أيام، يزداد بعد الوجبات...</p></div></div>
                <div className="soap-line"><bdi>A</bdi><div><strong>Assessment</strong><p>اشتباه التهاب معدة حاد مع حاجة لاستبعاد...</p></div></div>
                <div className="code-row"><span>ICD-10-AM</span><bdi>K29.70</bdi><bdi>R10.13</bdi></div>
              </div>
            </div>
            <div className="approval-card"><div className="approval-icon">✓</div><div><strong>الاعتماد بيد الطبيب</strong><span>لن تُرفع الزيارة قبل موافقتك</span></div></div>
            <div className="coding-card"><span>مطابقة ترميزية</span><strong><bdi>ICD-10-AM</bdi></strong><small>المصدر: كلام الزيارة</small></div>
          </div>
        </div>
        <div className="landing-shell standards"><span>مصمم للمنظومة الصحية السعودية</span><div><bdi>NPHIES</bdi><bdi>FHIR</bdi><bdi>ICD-10-AM</bdi><bdi>ACHI</bdi><bdi>SBS</bdi><bdi>SFDA</bdi><bdi>PDPL</bdi></div></div>
      </section>

      <section className="light-section" id="solution">
        <div className="landing-shell section-grid"><div className="section-heading"><span className="section-kicker">المسار الكامل</span><h2>من صوت العيادة<br />إلى ملف طبي مكتمل.</h2></div><p className="section-intro">منصة واحدة تغلق الفجوة بين الحوار العربي، التوثيق الإنجليزي، الترميز الطبي، ومتطلبات الرفع — دون أن تحول الطبيب إلى كاتب بيانات.</p></div>
        <div className="landing-shell benefits-grid">{benefits.map(([number,title,text,meta]) => <article className="benefit-card" key={number}><div className="benefit-top"><span>{number}</span><i aria-hidden="true">↙</i></div><h3>{title}</h3><p>{text}</p><small>{meta}</small></article>)}</div>
      </section>

      <section className="workflow" id="workflow">
        <div className="landing-shell workflow-shell">
          <div className="workflow-copy"><span className="section-kicker section-kicker-dark">رحلة بلا تعقيد</span><h2>أربع خطوات.<br />اعتماد واحد.</h2><p>يبقى الطبيب مع المريض، بينما يبني Medify التوثيق والإرشاد خلف المشهد. لا شاشات مزدحمة ولا نسخ ولصق بين الأنظمة.</p><Link className="text-link" href="/register">ابدأ مع منشأتك <span>←</span></Link></div>
          <div className="steps-list">{steps.map(([number,title,text]) => <article className="step" key={number}><span className="step-num">{number}</span><div><h3>{title}</h3><p>{text}</p></div><i>↙</i></article>)}</div>
        </div>
      </section>

      <section className="review-section">
        <div className="landing-shell review-grid">
          <div className="review-panel">
            <div className="review-toolbar"><span><i /> مراجعة الزيارة</span><bdi>SOAP · Auto-saved</bdi></div>
            <div className="review-body"><div className="review-sidebar"><span className="active">S</span><span>O</span><span>A</span><span>P</span></div><div className="review-content">
              <div className="review-title"><div><small>ASSESSMENT</small><h3>التقييم والخطة</h3></div><span>تم التحقق</span></div>
              <p>الأعراض والفحص السريري يتوافقان مع التهاب معدة حاد، مع توصية بمتابعة مؤشرات الإنذار.</p>
              <div className="guidance"><b>✦ إرشاد مضمّن</b><p>آخر تحليل للمريض يظهر انخفاضًا بسيطًا في الهيموغلوبين. راجع الحاجة لفحص إضافي.</p><small>المصدر: ملف المريض · تحليل CBC السابق</small></div>
              <div className="codes"><bdi>K29.70</bdi><bdi>R10.13</bdi><bdi>99214</bdi></div><button type="button">اعتمد وارفع <span>✓</span></button>
            </div></div>
          </div>
          <div className="review-copy"><span className="section-kicker">مساحة مراجعة واحدة</span><h2>الإرشاد حيث يحتاجه الطبيب، لا في شاشة أخرى.</h2><p>يظهر Medify الإرشاد السريري والترميزي مباشرة على الفقرة ذات الصلة، مع مصدر واضح من ملف المريض أو كلام الزيارة.</p><ul><li><span>✓</span> تعديل بالنص أو الصوت أو محادثة AI</li><li><span>✓</span> أكواد قابلة للمراجعة قبل الاعتماد</li><li><span>✓</span> إيصال حالة واضح بعد الرفع</li></ul></div>
        </div>
      </section>

      <section className="trust" id="trust">
        <div className="landing-shell trust-shell">
          <div className="trust-heading"><div><span className="section-kicker section-kicker-dark">الثقة جزء من البنية</span><h2>بيانات صحية محمية.<br />قرار سريري محفوظ.</h2></div></div>
          <div className="assurances"><article><span>✓</span><h3>قرار بشري أولًا</h3><p>لا تغادر بيانات الزيارة قبل اعتماد الطبيب النهائي.</p></article><article><span>✓</span><h3>سجل تدقيق كامل</h3><p>كل تعديل واعتماد ورفع موثق وقابل للمراجعة.</p></article><article><span>✓</span><h3>ثنائي اللغة</h3><p>واجهة ومحتوى سريري عربي/إنجليزي من البداية.</p></article></div>
          <div className="data-residency"><div><span className="sa-mark">SA</span><div><strong>بياناتك داخل المملكة</strong><small>بنية مصممة لمتطلبات الإقامة المحلية وحماية البيانات الشخصية</small></div></div><div className="data-tags"><bdi>PDPL</bdi><bdi>TLS 1.3</bdi><bdi>AES-256</bdi><bdi>RBAC</bdi></div></div>
        </div>
      </section>

      <section className="cta-section"><div className="landing-shell cta-box"><div><span>جاهزون لعيادة تجريبية</span><h2>أعد وقت الطبيب<br />إلى المريض.</h2><p>ابدأ عرضًا مخصصًا لمنشأتك، وشاهد الرحلة من الاستشارة إلى الرفع على بيئة تحاكي عملكم اليومي.</p></div><div className="cta-actions"><Link className="button button-primary" href="/register">اطلب عرضًا لمنشأتك <span>←</span></Link><Link className="cta-login" href="/login">لديك حساب؟ تسجيل الدخول</Link></div></div></section>

      <footer className="landing-footer"><div className="landing-shell footer-grid"><div><img src="/brand/medify-logo-reversed-transparent.png" alt="Medify" /><p>البنية التوثيقية الذكية للرعاية الصحية السعودية.</p></div><div><strong>المنتج</strong><a href="#solution">الحل</a><a href="#workflow">كيف يعمل</a><a href="#trust">الأمان</a></div><div><strong>ابدأ</strong><Link href="/register">تسجيل منشأة</Link><Link href="/login">تسجيل الدخول</Link></div><div className="footer-note"><span>صُمم في المملكة العربية السعودية</span><small>© 2026 Medify. جميع الحقوق محفوظة.</small></div></div></footer>
    </main>
  );
}
