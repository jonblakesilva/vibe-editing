import React from 'react';
import {CalculateMetadataFunction, Composition} from 'remotion';
import {BaseProps, defaultColors} from './shared';
import {KineticTitle} from './templates/KineticTitle';
import {LowerThird} from './templates/LowerThird';
import {ChapterCard} from './templates/ChapterCard';
import {CallToAction} from './templates/CallToAction';
import {Callout} from './templates/Callout';
import {BrandIntro} from './templates/BrandIntro';
import {EditorialTitle} from './templates/EditorialTitle';
import {FloatingCards} from './templates/FloatingCards';
import {StatPanels} from './templates/StatPanels';
import {EndCard} from './templates/EndCard';
import {Thumbnail} from './templates/Thumbnail';

// Size, fps and length come from the props file the Python renderer writes, so one
// template serves 16:9, 9:16 and 1:1 at any resolution.
const meta: CalculateMetadataFunction<BaseProps> = ({props}) => ({
  width: props.width,
  height: props.height,
  fps: props.fps,
  durationInFrames: props.durationInFrames,
});

const base: BaseProps = {width: 1920, height: 1080, fps: 30, durationInFrames: 105, colors: defaultColors};

export const Root: React.FC = () => (
  <>
    <Composition id="KineticTitle" component={KineticTitle as React.FC<any>} calculateMetadata={meta as any}
      width={1920} height={1080} fps={30} durationInFrames={105}
      defaultProps={{...base, text: 'THE BOOKED SOLID SYSTEM'}} />
    <Composition id="LowerThird" component={LowerThird as React.FC<any>} calculateMetadata={meta as any}
      width={1920} height={1080} fps={30} durationInFrames={135}
      defaultProps={{...base, durationInFrames: 135, name: 'Jonathan Silva', title: 'Founder, Booked Solid'}} />
    <Composition id="ChapterCard" component={ChapterCard as React.FC<any>} calculateMetadata={meta as any}
      width={1920} height={1080} fps={30} durationInFrames={75}
      defaultProps={{...base, durationInFrames: 75, number: 1, title: 'Answer every lead in five minutes'}} />
    <Composition id="CallToAction" component={CallToAction as React.FC<any>} calculateMetadata={meta as any}
      width={1920} height={1080} fps={30} durationInFrames={120}
      defaultProps={{...base, durationInFrames: 120, text: 'Book a free call', url: 'example.com'}} />
    <Composition id="Callout" component={Callout as React.FC<any>} calculateMetadata={meta as any}
      width={1920} height={1080} fps={30} durationInFrames={90}
      defaultProps={{...base, durationInFrames: 90, text: 'Reply within 5 minutes', label: 'Key point'}} />
    <Composition id="BrandIntro" component={BrandIntro as React.FC<any>} calculateMetadata={meta as any}
      width={1920} height={1080} fps={30} durationInFrames={75}
      defaultProps={{...base, durationInFrames: 75, brand: 'Booked Solid', tagline: 'Never miss a lead'}} />
    <Composition id="EditorialTitle" component={EditorialTitle as React.FC<any>} calculateMetadata={meta as any}
      width={1920} height={1080} fps={30} durationInFrames={105}
      defaultProps={{...base, text: 'What 25,000 doors taught me'}} />
    <Composition id="FloatingCards" component={FloatingCards as React.FC<any>} calculateMetadata={meta as any}
      width={1920} height={1080} fps={30} durationInFrames={120}
      defaultProps={{...base, durationInFrames: 120, cards: [{title: 'Missed Call Text-Back'}, {title: '5-Star Reviews'}, {title: 'AI Voice Agent'}, {title: 'Local SEO'}, {title: 'Revenue Reactivation'}]}} />
    <Composition id="StatPanels" component={StatPanels as React.FC<any>} calculateMetadata={meta as any}
      width={1920} height={1080} fps={30} durationInFrames={120}
      defaultProps={{...base, durationInFrames: 120, stats: [{value: '25,000', label: 'doors knocked'}, {value: '10,000+', label: 'homeowner conversations'}]}} />
    <Composition id="EndCard" component={EndCard as React.FC<any>} calculateMetadata={meta as any}
      width={1920} height={1080} fps={30} durationInFrames={120}
      defaultProps={{...base, durationInFrames: 120, text: 'Book a free strategy call', url: 'theleadventure.com', tagline: 'Built in the trades. Not in a marketing agency.'}} />
    <Composition id="Thumbnail" component={Thumbnail as React.FC<any>} calculateMetadata={meta as any}
      width={1280} height={720} fps={30} durationInFrames={1}
      defaultProps={{...base, width: 1280, height: 720, durationInFrames: 1, title: 'See your website before you buy', highlight: 'website'}} />
  </>
);
