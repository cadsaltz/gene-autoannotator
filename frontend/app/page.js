import AppShell from "../components/AppShell";
import CreditsSection from "../components/guide/CreditsSection";
import DisclaimerSection from "../components/guide/DisclaimerSection";
import FaqSection from "../components/guide/FaqSection";
import GuideToc from "../components/guide/GuideToc";
import HeroSection from "../components/guide/HeroSection";
import LimitsSection from "../components/guide/LimitsSection";
import PipelineSection from "../components/guide/PipelineSection";
import TradeoffsSection from "../components/guide/TradeoffsSection";
import TutorialSection from "../components/guide/TutorialSection";
import WhatYouGetSection from "../components/guide/WhatYouGetSection";

export default function Home() {
  return (
    <AppShell publicPage>
      <div className="guide grid grid-cols-1 gap-6 lg:grid-cols-[13.5rem_minmax(0,1fr)] lg:items-start lg:gap-8">
        <GuideToc />
        <article className="grid min-w-0 grid-cols-1 gap-14">
          <HeroSection />
          <WhatYouGetSection />
          <PipelineSection />
          <TutorialSection />
          <LimitsSection />
          <TradeoffsSection />
          <DisclaimerSection />
          <CreditsSection />
          <FaqSection />
        </article>
      </div>
    </AppShell>
  );
}
